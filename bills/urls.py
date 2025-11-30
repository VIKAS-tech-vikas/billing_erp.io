from django.urls import path
from . import views

urlpatterns = [

    # Authentication
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('', views.home, name='home'),

    # Billing
    path('create-bill/', views.create_bill, name='create_bill'),                     # create new bill
    path('add-items/<int:bill_id>/', views.add_items, name='add_items'),             # add/edit items page
    path('add-items/<int:bill_id>/generate/', views.add_items_generate, name='add_items_generate'),
    path('bill/<int:bill_id>/', views.bill_detail, name='bill_detail'),
    path('generate-bill/<int:bill_id>/', views.generate_bill, name='generate_bill'), # invoice print page

    # Customers
    path('add-customer/', views.add_customer, name='add_customer'),
    path('view-customers/', views.view_customers, name='view_customers'),
    path('customer/<int:customer_id>/', views.customer_detail, name='customer_detail'),
    path('edit-customer/<int:customer_id>/', views.edit_customer, name='edit_customer'),
    path('delete-customer/<int:customer_id>/', views.delete_customer, name='delete_customer'),

    # Goods Return
    path("bill/<int:bill_id>/return/", views.return_bill, name="return_bill"),

    # Mark Paid
    path('bill/<int:bill_id>/mark-paid/', views.mark_bill_paid, name='mark_bill_paid'),

    # Delete Bill
    path('bill/delete/<int:bill_id>/', views.delete_bill, name='delete_bill'),

    # Dual Invoice layout
    path("customer/<int:customer_id>/two-invoices/", views.two_invoices_view, name="two_invoices"),

    # Reports
    path('customer-statement/', views.customer_statement, name='customer_statement'),
    path('customer-monthly-statement/', views.customer_monthly_statement, name='customer_monthly_statement'),
    path("bill/<int:bill_id>/pay/", views.pay_bill, name="pay_bill"),
]
