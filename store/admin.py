from django.contrib import admin
from .models import Shop, Category, Product, Customer, Order, OrderItem, PaymentRequest

admin.site.register(Shop)
admin.site.register(Category)
admin.site.register(Product)
admin.site.register(Customer)
admin.site.register(Order)
admin.site.register(OrderItem)


@admin.register(PaymentRequest)
class PaymentRequestAdmin(admin.ModelAdmin):
    list_display = ['shop', 'plan_name', 'amount', 'payment_method', 'sender_number', 'transaction_id', 'status',
                    'created_at']
    list_filter = ['status', 'plan_name', 'payment_method']
    search_fields = ['shop__name', 'transaction_id', 'sender_number']
    actions = ['approve_payments', 'reject_payments']

    @admin.action(description='✅ Approve selected payments')
    def approve_payments(self, request, queryset):
        for req in queryset.filter(status='Pending'):
            shop = req.shop
            if req.plan_name == 'SMS Recharge':
                # ০.৪০ টাকা রেটে SMS যোগ হবে
                sms_added = int(float(req.amount) / 0.40)
                shop.sms_balance += sms_added
                shop.save(update_fields=['sms_balance'])
            else:
                # শুধু প্ল্যান আপডেট হবে, কোনো ফ্রি SMS পাবে না
                shop.subscription_plan = req.plan_name
                shop.save(update_fields=['subscription_plan'])

            req.status = 'Approved'
            req.save()
        self.message_user(request, "Payments Approved Successfully!")

    @admin.action(description='❌ Reject selected payments')
    def reject_payments(self, request, queryset):
        queryset.update(status='Rejected')
        self.message_user(request, "Selected payments have been rejected.")

    def save_model(self, request, obj, form, change):
        """
        Admin-এ inline edit করে status Approved করলেও update হবে।
        শুধু action button নয়, যেকোনোভাবে Approve করলেই কাজ করবে।
        """
        if change:
            try:
                old_obj = PaymentRequest.objects.get(pk=obj.pk)
                old_status = old_obj.status
            except PaymentRequest.DoesNotExist:
                old_status = None

            # Pending → Approved: Plan upgrade or SMS added
            if old_status == 'Pending' and obj.status == 'Approved':
                shop = obj.shop
                if obj.plan_name == 'SMS Recharge':
                    # ০.৪০ টাকা রেটে SMS যোগ হবে
                    sms_added = int(float(obj.amount) / 0.40)
                    shop.sms_balance += sms_added
                    shop.save(update_fields=['sms_balance'])
                else:
                    # শুধু প্ল্যান আপডেট হবে, কোনো ফ্রি SMS পাবে না
                    shop.subscription_plan = obj.plan_name
                    shop.save(update_fields=['subscription_plan'])

            # Approved → Rejected: plan Free-তে ফেরত (যদি SMS Recharge না হয়)
            elif old_status == 'Approved' and obj.status == 'Rejected':
                if obj.plan_name != 'SMS Recharge':
                    shop = obj.shop
                    shop.subscription_plan = 'Free'
                    shop.save(update_fields=['subscription_plan'])

        super().save_model(request, obj, form, change)

# Facebook Page Connection
from .models import FacebookPageConnection

@admin.register(FacebookPageConnection)
class FacebookPageConnectionAdmin(admin.ModelAdmin):
    list_display = ['shop', 'page_name', 'page_id', 'fan_count', 'is_active', 'connected_at']
    list_filter = ['is_active']
    search_fields = ['page_name', 'shop__name']
    readonly_fields = ['connected_at', 'updated_at']
