# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch
from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_company, create_customer
from erpnext.accounts.doctype.account.test_account import create_account
from frappe.utils import random_string
from erpnext.accounts.doctype.process_payment_reconciliation.process_payment_reconciliation import get_reconciled_count,get_pr_instance,trigger_job_for_doc,pause_job_for_doc,get_next_allocation,fetch_and_allocate
from frappe.utils import get_link_to_form
from frappe.utils.scheduler import is_scheduler_inactive


class TestProcessPaymentReconciliation(FrappeTestCase):
	def setUp(self):
		create_company()
		self.party_type = "Customer"
		self.party = create_customer("_Test Customer", currency="INR")
		account = frappe.get_doc("Account", "Creditors - _TC")
		self.receivable_payable_account = account.name
		self.company = "_Test Company"
		advance_account = create_account(
			parent_account="Current Assets - _TC",
			account_name="Advances Received",
			company="_Test Company",
			account_type="Receivable",
		)
		self.default_advance_account = advance_account

	def test_validate_receivable_payable_account_company_mismatch(self):
		# Setup test data
		company_1 = "_Test Company"
		company_2 = "Other Company " + random_string(5)

		# Create both companies
		for comp in [company_1, company_2]:
			if not frappe.db.exists("Company", comp):
				frappe.get_doc({
					"doctype": "Company",
					"company_name": comp,
					"default_currency": "INR"
				}).insert()

		# account = create_test_account("Receivable Account " + random_string(5), company_2)

		advance_account = create_account(
			parent_account="Current Assets - _TC",
			account_name="Advances Received",
			company="_Test Company",
			account_type="Receivable",
		)

		# Create test document
		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_2
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.receivable_payable_account = advance_account

		# Expect frappe.throw for mismatched company
		with self.assertRaises(frappe.exceptions.ValidationError):
			ppr.validate_receivable_payable_account()

	def test_validate_receivable_payable_account_valid(self):
		account = frappe.get_doc("Account", "Creditors - _TC")
		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = "_Test Company"
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.receivable_payable_account = account

		# Should not raise any exception
		ppr.validate_receivable_payable_account()

	def test_validate_bank_cash_account_company_mismatch(self):
		company_1 = "_Test Company"
		company_2 = "Another Co " + random_string(5)

		for comp in [company_1, company_2]:
			if not frappe.db.exists("Company", comp):
				frappe.get_doc({"doctype": "Company", "company_name": comp,"default_currency": "INR"}).insert()

		# account = create_test_account("Cash Account " + random_string(5), company_2)

		advance_account = create_account(
			parent_account="Current Assets - _TC",
			account_name="Cash Account",
			company=company_1,
			account_type="Receivable",
		)

		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_2
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.bank_cash_account = advance_account

		with self.assertRaises(frappe.exceptions.ValidationError):
			ppr.validate_bank_cash_account()
	

	def test_before_save_clears_fields(self):
		doc =make_process_paymentreconciliation()
		# Call before_save
		doc.before_save()
		self.assertEqual(doc.status, "")
		self.assertEqual(doc.error_log, "")

	def test_on_submit_sets_status_and_error_log(self):
		# Create and insert a dummy record
		doc =make_process_paymentreconciliation()

		# Call on_submit
		doc.on_submit()

		# Fetch from DB to confirm persisted values
		status = frappe.db.get_value("Process Payment Reconciliation", doc.name, "status")
		error_log = frappe.db.get_value("Process Payment Reconciliation", doc.name, "error_log")
		self.assertEqual(status, "Queued")
		self.assertEqual(error_log, None)

	def test_on_cancel_updates_log_status(self):
		# Create base Process Payment Reconciliation doc
		doc =make_process_paymentreconciliation()

		# Create a linked log record
		log_doc = frappe.get_doc({
			"doctype": "Process Payment Reconciliation Log",
			"process_pr": doc.name,
			"status": "Running",
		})
		log_doc.insert(ignore_if_duplicate=True)

		# Call on_cancel
		doc.on_cancel()

		# Assert main doc is cancelled
		main_status = frappe.db.get_value("Process Payment Reconciliation", doc.name, "status")
		self.assertEqual(main_status, "Cancelled")

		# Assert log also cancelled
		log_status = frappe.db.get_value("Process Payment Reconciliation Log", log_doc.name, "status")
		self.assertEqual(log_status, "Cancelled")

	def test_valid_docname(self):
		"""Test when a valid docname is provided"""
		doc =make_process_paymentreconciliation()
		result = get_reconciled_count(doc.name)
		reconcile_log = frappe.get_doc({
			"doctype": "Process Payment Reconciliation Log",
			"process_pr": doc.name,
			"status": "Running",
			"reconciled_entries": 5,
			"total_allocations": 10,
		})
		reconcile_log.insert(ignore_if_duplicate=True)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["processed"], 5)
		self.assertEqual(result["total"], 10)

		invalid_result = get_reconciled_count("INVALID_DOCNAME")
		self.assertEqual(invalid_result, {})

		empty_result = get_reconciled_count()
		self.assertEqual(empty_result, {})

	def test_get_pr_instance(self):
		"""Test that get_pr_instance copies fields correctly"""
		doc =make_process_paymentreconciliation()
		pr = get_pr_instance(doc.name)

		# Check that Payment Reconciliation doc was created
		self.assertEqual(pr.doctype, "Payment Reconciliation")

		# Verify field values were copied properly
		self.assertEqual(pr.company, doc.company)
		self.assertEqual(pr.party_type, doc.party_type)
		self.assertEqual(pr.party, doc.party)
		self.assertEqual(pr.receivable_payable_account, doc.receivable_payable_account)
		self.assertEqual(pr.default_advance_account, doc.default_advance_account)
		self.assertEqual(pr.from_invoice_date, doc.from_invoice_date)
		self.assertEqual(pr.to_invoice_date, doc.to_invoice_date)
		self.assertEqual(pr.from_payment_date, doc.from_payment_date)
		self.assertEqual(pr.to_payment_date, doc.to_payment_date)

		# Verify default values
		self.assertEqual(pr.invoice_limit, 1000)
		self.assertEqual(pr.payment_limit, 1000)

	def test_no_docname(self):
		"""Should do nothing if no docname is provided"""
		result = trigger_job_for_doc(None)
		self.assertIsNone(result)

		frappe.db.get_single_value = lambda *a, **kw: 0  # Mock disabled setting
		self.assertRaises(frappe.ValidationError, check_auto_reconcile_enabled)

		frappe.db.get_single_value = lambda *a, **kw: 1  # Mock enabled setting
		try:
			check_auto_reconcile_enabled()
		except frappe.ValidationError:
			self.fail("check_auto_reconcile_enabled() raised ValidationError unexpectedly!")

	@patch("erpnext.accounts.frappe.db.get_single_value", return_value=False)
	def test_auto_reconcile_disabled(self, mock_setting):
		"""Should throw if auto reconciliation is disabled"""
		doc = make_process_paymentreconciliation()
		with self.assertRaises(frappe.ValidationError):
			trigger_job_for_doc(doc.name)

	# @patch("erpnext.accounts.is_scheduler_inactive", return_value=True)
	# @patch("erpnext.accounts.frappe.msgprint")
	# def test_scheduler_inactive(self, mock_msgprint, mock_scheduler):
	# 	"""Should show msgprint if scheduler is inactive"""
	# 	doc = make_process_paymentreconciliation()
	# 	trigger_job_for_doc(doc.name)
	# 	mock_msgprint.assert_called_once()

	@patch("erpnext.accounts.is_scheduler_inactive", return_value=False)
	@patch("erpnext.accounts.is_job_running", return_value=False)
	@patch("erpnext.accounts.frappe.db.get_single_value", return_value=True)
	@patch("erpnext.accounts.frappe.enqueue")
	def test_trigger_for_queued_doc(self, mock_enqueue, mock_setting, mock_job_running, mock_scheduler):
		"""Should enqueue background job for queued doc"""
		doc = make_process_paymentreconciliation()
		doc.db_set("status", "Queued")
		trigger_job_for_doc(doc.name)

		mock_enqueue.assert_called_once()
		args, kwargs = mock_enqueue.call_args
		self.assertIn("reconcile_based_on_filters", kwargs["method"])
		self.assertIn(doc.name, kwargs["job_name"])

	@patch("erpnext.accounts.is_scheduler_inactive", return_value=False)
	@patch("erpnext.accounts.is_job_running", return_value=False)
	@patch("erpnext.accounts.frappe.db.get_single_value", return_value=True)
	@patch("erpnext.accounts.frappe.enqueue")
	def test_trigger_for_paused_doc(self, mock_enqueue, mock_setting, mock_job_running, mock_scheduler):
		"""Should resume and enqueue job when status is Paused"""
		doc = make_process_paymentreconciliation()
		doc.db_set("status", "Paused")

		trigger_job_for_doc(doc.name)
		mock_enqueue.assert_called_once()
		args, kwargs = mock_enqueue.call_args
		self.assertIn(doc.name, kwargs["job_name"])

	def test_pause_job_updates_main_doc(self):
		"""Test that the Process Payment Reconciliation is marked as Paused"""
		doc = make_process_paymentreconciliation()
		pause_job_for_doc(doc.name)

		status = frappe.db.get_value("Process Payment Reconciliation", doc.name, "status")
		self.assertEqual(status, "Paused")

		pause_job_for_doc(None)
		self.assertTrue(True)
	
	def test_returns_empty_list_when_log_is_none(self):
		"""If log is None, should return empty list"""
		result = get_next_allocation(None)
		self.assertEqual(result, [])

	@patch("erpnext.accounts.frappe.db.get_all")
	def test_returns_empty_list_when_no_unreconciled_records(self, mock_get_all):
		"""If no unreconciled allocations exist, return empty list"""
		mock_get_all.return_value = []  # No next allocation
		result = get_next_allocation("LOG-001")
		self.assertEqual(result, [])
		mock_get_all.assert_called_once()  # Only the first query runs
	
	@patch("erpnext.accounts.frappe.db.get_all")
	def test_returns_allocations_for_next_reference(self, mock_get_all):
		"""Should return list of allocations matching first unreconciled record"""
		# First call (to get the 'next' allocation)
		doc = make_process_paymentreconciliation()
		first_unreconciled = [{
			"reference_type": "Process Payment Reconciliation",
			"reference_name": doc.name
		}]

		# Second call (to get all allocations with same ref)
		all_allocations = [
			{
				"name": "ALLOC-001",
				"parent": "LOG-001",
				"reference_type": "Process Payment Reconciliation",
				"reference_name": doc.name,
				"reconciled": 0,
				"idx": 1,
			},
			{
				"name": "ALLOC-002",
				"parent": "LOG-001",
				"reference_type": "Process Payment Reconciliation",
				"reference_name": doc.name,
				"reconciled": 0,
				"idx": 2,
			},
		]

		# Simulate two sequential calls to frappe.db.get_all
		mock_get_all.side_effect = [first_unreconciled, all_allocations]

		result = get_next_allocation("LOG-001")

		# Verify both DB calls
		self.assertEqual(mock_get_all.call_count, 2)
		self.assertEqual(result, all_allocations)

		# Ensure correct query order and filters
		first_call_args = mock_get_all.call_args_list[0][1]
		second_call_args = mock_get_all.call_args_list[1][1]

		self.assertIn("filters", first_call_args)
		self.assertIn("filters", second_call_args)
		self.assertEqual(second_call_args["filters"]["reference_name"], doc.name)

	@patch("erpnext.accounts.get_pr_instance")
	@patch("erpnext.accounts.frappe.get_doc")
	@patch("erpnext.accounts.frappe.db.get_value")
	@patch("erpnext.accounts.get_next_allocation")
	@patch("erpnext.accounts.is_job_running")
	@patch("erpnext.accounts.frappe.enqueue")
	def test_fetch_and_allocate_success(
		self,
		mock_enqueue,
		mock_is_job_running,
		mock_get_next_allocation,
		mock_get_value,
		mock_get_doc,
		mock_get_pr_instance,
	):
		"""Should fetch data, create allocations, and enqueue reconciliation job"""
		doc = make_process_paymentreconciliation()
		docname = doc.name
		log_name = "LOG-001"

		# --- Mock frappe.db.get_value ---
		def get_value_side_effect(doctype, *args, **kwargs):
			if doctype == "Process Payment Reconciliation Log":
				if kwargs.get("filters"):
					return log_name  # log exists for doc
				if args and args[0] == log_name and args[1] == "allocated":
					return False  # Not yet allocated
			return None

		mock_get_value.side_effect = get_value_side_effect

		# --- Mock reconcile_log (Frappe Doc) ---
		reconcile_log = MagicMock()
		reconcile_log.name = log_name
		reconcile_log.get.return_value = []
		mock_get_doc.return_value = reconcile_log

		# --- Mock PR instance ---
		pr_mock = MagicMock()
		pr_mock.invoices = [MagicMock(), MagicMock()]
		pr_mock.payments = [MagicMock()]
		pr_mock.allocate_entries = MagicMock()
		pr_mock.get.return_value = [MagicMock()]
		mock_get_pr_instance.return_value = pr_mock

		# --- Mock get_next_allocation ---
		mock_get_next_allocation.return_value = [
			frappe._dict({"idx": 1}),
			frappe._dict({"idx": 2}),
		]

		# --- Mock job running & enqueue ---
		mock_is_job_running.return_value = False

		# --- Call the function ---
		fetch_and_allocate(docname)

		# --- Assertions ---
		# Ensures allocation data fetched
		mock_get_pr_instance.assert_called_once_with(docname)
		pr_mock.get_unreconciled_entries.assert_called_once()

		# Allocations appended and saved
		self.assertTrue(reconcile_log.save.called)
		self.assertEqual(reconcile_log.allocated, True)
		self.assertIsInstance(reconcile_log.total_allocations, int)

		# Job enqueue verification
		mock_enqueue.assert_called_once()
		args, kwargs = mock_enqueue.call_args
		self.assertIn("method", kwargs)
		self.assertIn("job_name", kwargs)
		self.assertTrue(kwargs["job_name"].startswith(f"process_{docname}_reconcile_allocation_"))
	
	@patch("erpnext.accounts.frappe.db.get_value")
	def test_fetch_and_allocate_with_no_log(self, mock_get_value):
		"""Should return gracefully when no log exists"""
		mock_get_value.return_value = None
		fetch_and_allocate("PR-001")
		mock_get_value.assert_called()
	
	@patch("erpnext.accounts.frappe.db.get_value")
	def test_fetch_and_allocate_with_no_doc(self, mock_get_value):
		"""Should return without errors when docname is None"""
		fetch_and_allocate(None)
		mock_get_value.assert_not_called()

	@patch("frappe.msgprint")
	@patch("erpnext.accounts.is_scheduler_inactive", return_value=True)
	def test_scheduler_inactive(self, mock_scheduler, mock_msgprint):
		doc = make_process_paymentreconciliation()
		process_payment_reconciliation(doc.name)
		mock_msgprint.assert_called_once_with("Scheduler is Inactive. Can't trigger job now.")

	@patch("frappe.enqueue")
	@patch("erpnext.accounts.is_job_running", return_value=False)
	@patch("erpnext.accounts.is_scheduler_inactive", return_value=False)
	@patch("frappe.db.set_value")
	@patch("frappe.db.get_value", return_value="Queued")
	def test_status_queued_should_enqueue(
		self, mock_get_value, mock_set_value, mock_scheduler, mock_job_running, mock_enqueue
	):
		doc = make_process_paymentreconciliation()
		process_payment_reconciliation(doc.name)

		mock_set_value.assert_any_call("Process Payment Reconciliation", doc.name, "status", "Running")
		mock_enqueue.assert_called_once()
		job_name = mock_enqueue.call_args.kwargs.get("job_name")
		self.assertEqual(job_name, f"start_processing_{doc.name}")

	@patch("frappe.enqueue")
	@patch("erpnext.accounts.is_job_running", return_value=False)
	@patch("erpnext.accounts.is_scheduler_inactive", return_value=False)
	def test_status_paused_should_update_log_and_enqueue(self, mock_scheduler, mock_job_running, mock_enqueue):
		def mock_get_value(doctype, name=None, field=None, filters=None):
			if doctype == "Process Payment Reconciliation":
				return "Paused"
			if doctype == "Process Payment Reconciliation Log":
				return "LOG-0001"
			return None

		with patch("frappe.db.get_value", side_effect=mock_get_value) as mock_get, patch(
			"frappe.db.set_value"
		) as mock_set:
			doc = make_process_paymentreconciliation()
			process_payment_reconciliation(doc.name)

			mock_set.assert_any_call("Process Payment Reconciliation", doc.name, "status", "Running")
			mock_set.assert_any_call("Process Payment Reconciliation Log", "LOG-0001", "status", "Running")
			mock_enqueue.assert_called_once()
			job_name = mock_enqueue.call_args.kwargs.get("job_name")
			self.assertEqual(job_name, f"start_processing_{doc.name}")

def make_process_paymentreconciliation():
	ppr = frappe.new_doc("Process Payment Reconciliation")
	ppr.company = "_Test Company"
	ppr.party_type = "Customer"
	ppr.party = "_Test Customer"
	account = frappe.get_doc("Account", "Creditors - _TC")
	ppr.receivable_payable_account = account.name
	advance_account = create_account(
			parent_account="Current Assets - _TC",
			account_name="Advances Received",
			company="_Test Company",
			account_type="Receivable",
		)
	ppr.default_advance_account = advance_account
	ppr.insert(ignore_if_duplicate=True,ignore_permissions=True)

	return ppr

def create_test_account(account_name, company):
	account = frappe.get_doc({
		"doctype": "Account",
		"account_name": account_name,
		"company": company,
		"account_type": "Receivable",
		"root_type": "Asset",
		"is_group": 0,
	})
	account.insert(ignore_if_duplicate=True)
	return account.name

def check_auto_reconcile_enabled():
	if not frappe.db.get_single_value("Accounts Settings", "auto_reconcile_payments"):
		frappe.throw(
			_("Auto Reconciliation of Payments has been disabled. Enable it through {0}").format(
				get_link_to_form("Accounts Settings", "Accounts Settings")
			)
		)
		return

def process_payment_reconciliation(docname):
	if not is_scheduler_inactive():
		status = frappe.db.get_value("Process Payment Reconciliation", docname, "status")

		if status == "Queued":
			frappe.db.set_value("Process Payment Reconciliation", docname, "status", "Running")
			job_name = f"start_processing_{docname}"
			if not is_job_running(job_name):
				frappe.enqueue(
					method="erpnext.accounts.doctype.process_payment_reconciliation.process_payment_reconciliation.reconcile_based_on_filters",
					queue="long",
					is_async=True,
					job_name=job_name,
					enqueue_after_commit=True,
					doc=docname,
				)

		elif status == "Paused":
			frappe.db.set_value("Process Payment Reconciliation", docname, "status", "Running")
			log = frappe.db.get_value("Process Payment Reconciliation Log", filters={"process_pr": docname})
			if log:
				frappe.db.set_value("Process Payment Reconciliation Log", log, "status", "Running")

			job_name = f"start_processing_{docname}"
			if not is_job_running(job_name):
				frappe.enqueue(
					method="erpnext.accounts.doctype.process_payment_reconciliation.process_payment_reconciliation.reconcile_based_on_filters",
					queue="long",
					is_async=True,
					job_name=job_name,
					doc=docname,
				)
	else:
		frappe.msgprint(_("Scheduler is Inactive. Can't trigger job now."))
