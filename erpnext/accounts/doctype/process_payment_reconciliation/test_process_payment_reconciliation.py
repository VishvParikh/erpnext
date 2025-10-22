# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_company, create_customer
from erpnext.accounts.doctype.account.test_account import create_account
from frappe.utils import random_string
from erpnext.accounts.doctype.process_payment_reconciliation.process_payment_reconciliation import get_reconciled_count,get_pr_instance,trigger_job_for_doc

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
		company_1 = "Test Company " + random_string(5)
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
			company=company_2,
			account_type="Receivable",
		)

		# Create test document
		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_1
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.receivable_payable_account = advance_account

		# Expect frappe.throw for mismatched company
		with self.assertRaises(ValidationError):
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
		company_1 = "Main Co " + random_string(5)
		company_2 = "Another Co " + random_string(5)

		for comp in [company_1, company_2]:
			if not frappe.db.exists("Company", comp):
				frappe.get_doc({"doctype": "Company", "company_name": comp,"default_currency": "INR"}).insert()

		# account = create_test_account("Cash Account " + random_string(5), company_2)

		advance_account = create_account(
			parent_account="Current Assets - _TC",
			account_name="Cash Account",
			company=company_2,
			account_type="Receivable",
		)

		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_1
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.bank_cash_account = advance_account

		with self.assertRaises(ValidationError):
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

	@patch("erpnext.accounts.frappe.db.get_single_value", return_value=False)
	def test_auto_reconcile_disabled(self, mock_setting):
		"""Should throw if auto reconciliation is disabled"""
		doc = make_process_paymentreconciliation()
		with self.assertRaises(frappe.ValidationError):
			trigger_job_for_doc(doc.name)

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
