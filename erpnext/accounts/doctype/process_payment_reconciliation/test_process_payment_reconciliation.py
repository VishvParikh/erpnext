# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_company, create_customer
from erpnext.accounts.doctype.account.test_account import create_account
import pytest
from frappe.utils import random_string

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

	@pytest.mark.unit
	def test_validate_receivable_payable_account_company_mismatch():
		# Setup test data
		company_1 = "Test Company " + random_string(5)
		company_2 = "Other Company " + random_string(5)

		# Create both companies
		for comp in [company_1, company_2]:
			if not frappe.db.exists("Company", comp):
				frappe.get_doc({
					"doctype": "Company",
					"company_name": comp
				}).insert()

		account = create_test_account("Receivable Account " + random_string(5), company_2)

		# Create test document
		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_1
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.receivable_payable_account = account

		# Expect frappe.throw for mismatched company
		with pytest.raises(frappe.ValidationError) as exc_info:
			ppr.validate_receivable_payable_account()

		assert "doesn't belong to company" in str(exc_info.value)


	@pytest.mark.unit
	def test_validate_receivable_payable_account_valid():
		account = frappe.get_doc("Account", "Creditors - _TC")
		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = "_Test Company"
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.receivable_payable_account = account

		# Should not raise any exception
		ppr.validate_receivable_payable_account()


	@pytest.mark.unit
	def test_validate_bank_cash_account_company_mismatch():
		company_1 = "Main Co " + random_string(5)
		company_2 = "Another Co " + random_string(5)

		for comp in [company_1, company_2]:
			if not frappe.db.exists("Company", comp):
				frappe.get_doc({"doctype": "Company", "company_name": comp}).insert()

		account = create_test_account("Cash Account " + random_string(5), company_2)

		ppr = frappe.new_doc("Process Payment Reconciliation")
		ppr.company = company_1
		ppr.party_type = "Customer"
		ppr.party = "_Test Customer"
		ppr.bank_cash_account = account

		with pytest.raises(frappe.ValidationError) as exc_info:
			ppr.validate_bank_cash_account()

		assert "doesn't belong to company" in str(exc_info.value)

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
		"parent_account": "Current Assets - " + company[:3],  # adjust parent if needed
		"account_type": "Receivable",
		"root_type": "Asset",
		"is_group": 0,
	})
	account.insert(ignore_if_duplicate=True)
	return account.name
