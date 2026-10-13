"""
Management command to populate the marketplace with sample templates.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from apps.templates_app.models import MarketplaceTemplate, TemplateReview
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = 'Populate marketplace with sample templates'

    def handle(self, *args, **options):
        self.stdout.write('Populating marketplace with sample templates...')

        # Sample templates data
        templates_data = [
            {
                'title': 'Modern Blue Invoice',
                'description': 'A clean, modern invoice template with blue accents. Perfect for professional services and consulting businesses.',
                'template_type': 'system',
                'price': 0,
                'demo_html': '''
                    <div style="font-family: 'Inter', sans-serif; max-width: 600px; margin: 0 auto; padding: 40px; background: white; border: 1px solid #e5e7eb; border-radius: 8px;">
                        <header style="border-bottom: 3px solid #2563eb; padding-bottom: 20px; margin-bottom: 30px;">
                            <div style="display: flex; justify-content: space-between; align-items: start;">
                                <div>
                                    <h1 style="color: #2563eb; font-size: 28px; margin: 0; font-weight: 700;">INVOICE</h1>
                                    <p style="color: #6b7280; margin: 5px 0 0 0; font-size: 14px;">Invoice #12345</p>
                                </div>
                                <div style="text-align: right;">
                                    <h2 style="color: #111827; font-size: 20px; margin: 0; font-weight: 600;">Your Company</h2>
                                    <p style="color: #6b7280; margin: 2px 0; font-size: 13px;">123 Business St<br>City, State 12345</p>
                                </div>
                            </div>
                        </header>

                        <div style="display: flex; justify-content: space-between; margin-bottom: 30px;">
                            <div>
                                <h3 style="color: #111827; font-size: 16px; margin: 0 0 10px 0; font-weight: 600;">Bill To:</h3>
                                <p style="margin: 0; color: #111827; font-weight: 500;">Client Name</p>
                                <p style="margin: 2px 0; color: #6b7280; font-size: 13px;">Client Company<br>456 Client Ave<br>Client City, State 67890</p>
                            </div>
                            <div style="text-align: right;">
                                <div style="margin-bottom: 15px;">
                                    <span style="color: #6b7280; font-size: 13px;">Date:</span>
                                    <span style="color: #111827; font-weight: 500; margin-left: 10px;">Jan 15, 2024</span>
                                </div>
                                <div>
                                    <span style="color: #6b7280; font-size: 13px;">Due Date:</span>
                                    <span style="color: #111827; font-weight: 500; margin-left: 10px;">Feb 15, 2024</span>
                                </div>
                            </div>
                        </div>

                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px;">
                            <thead>
                                <tr style="background: #f3f4f6;">
                                    <th style="padding: 12px; text-align: left; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb;">Description</th>
                                    <th style="padding: 12px; text-align: center; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb;">Qty</th>
                                    <th style="padding: 12px; text-align: right; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb;">Price</th>
                                    <th style="padding: 12px; text-align: right; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb;">Total</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #111827;">Web Development Services</td>
                                    <td style="padding: 12px; text-align: center; border-bottom: 1px solid #e5e7eb; color: #111827;">10</td>
                                    <td style="padding: 12px; text-align: right; border-bottom: 1px solid #e5e7eb; color: #111827;">$50.00</td>
                                    <td style="padding: 12px; text-align: right; border-bottom: 1px solid #e5e7eb; color: #111827; font-weight: 600;">$500.00</td>
                                </tr>
                                <tr>
                                    <td style="padding: 12px; border-bottom: 1px solid #e5e7eb; color: #111827;">Monthly Maintenance</td>
                                    <td style="padding: 12px; text-align: center; border-bottom: 1px solid #e5e7eb; color: #111827;">1</td>
                                    <td style="padding: 12px; text-align: right; border-bottom: 1px solid #e5e7eb; color: #111827;">$200.00</td>
                                    <td style="padding: 12px; text-align: right; border-bottom: 1px solid #e5e7eb; color: #111827; font-weight: 600;">$200.00</td>
                                </tr>
                            </tbody>
                        </table>

                        <div style="display: flex; justify-content: flex-end; margin-bottom: 30px;">
                            <div style="width: 200px;">
                                <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb;">
                                    <span style="color: #6b7280;">Subtotal:</span>
                                    <span style="color: #111827; font-weight: 500;">$700.00</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #e5e7eb;">
                                    <span style="color: #6b7280;">Tax (10%):</span>
                                    <span style="color: #111827; font-weight: 500;">$70.00</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 2px solid #2563eb; margin-top: 8px;">
                                    <span style="color: #111827; font-weight: 600;">Total:</span>
                                    <span style="color: #2563eb; font-weight: 700; font-size: 18px;">$770.00</span>
                                </div>
                            </div>
                        </div>

                        <footer style="text-align: center; color: #6b7280; font-size: 12px; border-top: 1px solid #e5e7eb; padding-top: 20px;">
                            <p>Thank you for your business! Payment terms: Net 30 days.</p>
                        </footer>
                    </div>
                ''',
                'tags': ['modern', 'blue', 'professional', 'clean'],
                'compatible_types': ['invoice', 'quote'],
                'download_count': 1250,
                'rating': 4.8,
                'review_count': 89,
            },
            {
                'title': 'Classic Corporate',
                'description': 'Traditional corporate invoice template with formal styling. Ideal for established businesses and B2B transactions.',
                'template_type': 'system',
                'price': 0,
                'demo_html': '''
                    <div style="font-family: 'Times New Roman', serif; max-width: 700px; margin: 0 auto; padding: 50px; background: white; border: 2px solid #1f2937;">
                        <header style="text-align: center; margin-bottom: 40px; border-bottom: 1px solid #1f2937; padding-bottom: 20px;">
                            <h1 style="color: #1f2937; font-size: 32px; margin: 0; font-weight: normal; letter-spacing: 2px;">INVOICE</h1>
                            <p style="color: #6b7280; margin: 10px 0 0 0; font-size: 14px;">Invoice Number: INV-2024-001</p>
                        </header>

                        <div style="display: flex; justify-content: space-between; margin-bottom: 40px;">
                            <div style="flex: 1;">
                                <h3 style="color: #1f2937; font-size: 14px; margin: 0 0 10px 0; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">From:</h3>
                                <div style="color: #374151; line-height: 1.5;">
                                    <strong>ABC Corporation</strong><br>
                                    123 Corporate Boulevard<br>
                                    Business City, BC 12345<br>
                                    Phone: (555) 123-4567<br>
                                    Email: billing@abc-corp.com
                                </div>
                            </div>
                            <div style="flex: 1; text-align: right;">
                                <h3 style="color: #1f2937; font-size: 14px; margin: 0 0 10px 0; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;">Bill To:</h3>
                                <div style="color: #374151; line-height: 1.5;">
                                    <strong>Client Company Ltd.</strong><br>
                                    456 Customer Street<br>
                                    Client Town, CT 67890<br>
                                    Attention: John Smith<br>
                                    Phone: (555) 987-6543
                                </div>
                            </div>
                        </div>

                        <div style="margin-bottom: 40px; padding: 20px; background: #f9fafb; border: 1px solid #e5e7eb;">
                            <div style="display: flex; justify-content: space-between;">
                                <div>
                                    <strong style="color: #1f2937;">Invoice Date:</strong> January 15, 2024<br>
                                    <strong style="color: #1f2937;">Due Date:</strong> February 14, 2024<br>
                                    <strong style="color: #1f2937;">Terms:</strong> Net 30 days
                                </div>
                            </div>
                        </div>

                        <table style="width: 100%; border-collapse: collapse; margin-bottom: 40px; border: 1px solid #1f2937;">
                            <thead>
                                <tr style="background: #1f2937; color: white;">
                                    <th style="padding: 15px; text-align: left; font-weight: bold; border: 1px solid #1f2937;">Description</th>
                                    <th style="padding: 15px; text-align: center; font-weight: bold; border: 1px solid #1f2937;">Quantity</th>
                                    <th style="padding: 15px; text-align: right; font-weight: bold; border: 1px solid #1f2937;">Unit Price</th>
                                    <th style="padding: 15px; text-align: right; font-weight: bold; border: 1px solid #1f2937;">Amount</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td style="padding: 15px; border: 1px solid #e5e7eb; color: #374151;">Professional Consulting Services - January 2024</td>
                                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; color: #374151;">40</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; color: #374151;">$125.00</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; color: #374151; font-weight: bold;">$5,000.00</td>
                                </tr>
                                <tr>
                                    <td style="padding: 15px; border: 1px solid #e5e7eb; color: #374151;">Expense Reimbursement - Travel</td>
                                    <td style="padding: 15px; text-align: center; border: 1px solid #e5e7eb; color: #374151;">1</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; color: #374151;">$450.00</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; color: #374151; font-weight: bold;">$450.00</td>
                                </tr>
                                <tr style="background: #f9fafb;">
                                    <td colspan="3" style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; font-weight: bold; color: #1f2937;">Subtotal:</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; font-weight: bold; color: #1f2937;">$5,450.00</td>
                                </tr>
                                <tr style="background: #f9fafb;">
                                    <td colspan="3" style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; font-weight: bold; color: #1f2937;">Tax (8.5%):</td>
                                    <td style="padding: 15px; text-align: right; border: 1px solid #e5e7eb; font-weight: bold; color: #1f2937;">$463.25</td>
                                </tr>
                                <tr style="background: #1f2937; color: white;">
                                    <td colspan="3" style="padding: 15px; text-align: right; font-weight: bold; font-size: 16px;">TOTAL DUE:</td>
                                    <td style="padding: 15px; text-align: right; font-weight: bold; font-size: 16px;">$5,913.25</td>
                                </tr>
                            </tbody>
                        </table>

                        <footer style="text-align: center; color: #6b7280; font-size: 12px; border-top: 1px solid #e5e7eb; padding-top: 30px; font-style: italic;">
                            <p>Thank you for choosing ABC Corporation. For questions about this invoice, please contact our billing department at billing@abc-corp.com or (555) 123-4567.</p>
                            <p style="margin-top: 10px;">Make all checks payable to ABC Corporation. Payment is due within 30 days of invoice date.</p>
                        </footer>
                    </div>
                ''',
                'tags': ['corporate', 'traditional', 'formal', 'classic'],
                'compatible_types': ['invoice', 'quote'],
                'download_count': 890,
                'rating': 4.6,
                'review_count': 67,
            },
            {
                'title': 'Minimalist Green',
                'description': 'Clean and minimalist design with green accents. Perfect for eco-friendly businesses and modern startups.',
                'template_type': 'system',
                'price': 0,
                'demo_html': '''
                    <div style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 30px; background: white;">
                        <header style="margin-bottom: 40px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h1 style="color: #059669; font-size: 36px; margin: 0; font-weight: 300; letter-spacing: -1px;">Invoice</h1>
                                    <p style="color: #6b7280; margin: 5px 0 0 0; font-size: 14px;">#2024-001</p>
                                </div>
                                <div style="text-align: right;">
                                    <h2 style="color: #111827; font-size: 18px; margin: 0; font-weight: 500;">GreenTech Solutions</h2>
                                    <p style="color: #6b7280; margin: 2px 0; font-size: 12px;">123 Eco Street<br>Sustainable City, SC 12345</p>
                                </div>
                            </div>
                        </header>

                        <div style="margin-bottom: 40px;">
                            <div style="display: inline-block; background: #f0fdf4; padding: 20px; border-radius: 8px;">
                                <div style="margin-bottom: 15px;">
                                    <span style="color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Billed to</span>
                                    <h3 style="color: #111827; font-size: 16px; margin: 5px 0 0 0; font-weight: 600;">EcoClient Inc.</h3>
                                    <p style="color: #6b7280; margin: 2px 0; font-size: 13px;">789 Green Avenue<br>Eco Town, ET 67890</p>
                                </div>
                                <div style="display: flex; gap: 30px;">
                                    <div>
                                        <span style="color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Date</span>
                                        <p style="color: #111827; margin: 2px 0; font-size: 14px; font-weight: 500;">Jan 15, 2024</p>
                                    </div>
                                    <div>
                                        <span style="color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Due</span>
                                        <p style="color: #111827; margin: 2px 0; font-size: 14px; font-weight: 500;">Feb 15, 2024</p>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="margin-bottom: 40px;">
                            <table style="width: 100%; border-collapse: collapse;">
                                <thead>
                                    <tr>
                                        <th style="padding: 12px 0; text-align: left; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Service</th>
                                        <th style="padding: 12px 0; text-align: center; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Qty</th>
                                        <th style="padding: 12px 0; text-align: right; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Rate</th>
                                        <th style="padding: 12px 0; text-align: right; font-weight: 600; color: #111827; border-bottom: 1px solid #e5e7eb; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;">Amount</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr>
                                        <td style="padding: 16px 0; color: #111827; border-bottom: 1px solid #f3f4f6;">
                                            <div style="font-weight: 500;">Sustainable Web Development</div>
                                            <div style="color: #6b7280; font-size: 13px; margin-top: 2px;">Eco-friendly website development with green hosting</div>
                                        </td>
                                        <td style="padding: 16px 0; text-align: center; color: #111827; border-bottom: 1px solid #f3f4f6;">1</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6;">$2,500</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6; font-weight: 600;">$2,500</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 16px 0; color: #111827; border-bottom: 1px solid #f3f4f6;">
                                            <div style="font-weight: 500;">SEO Optimization</div>
                                            <div style="color: #6b7280; font-size: 13px; margin-top: 2px;">Organic search optimization for sustainability keywords</div>
                                        </td>
                                        <td style="padding: 16px 0; text-align: center; color: #111827; border-bottom: 1px solid #f3f4f6;">1</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6;">$800</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6; font-weight: 600;">$800</td>
                                    </tr>
                                    <tr>
                                        <td style="padding: 16px 0; color: #111827; border-bottom: 1px solid #f3f4f6;">
                                            <div style="font-weight: 500;">Monthly Maintenance</div>
                                            <div style="color: #6b7280; font-size: 13px; margin-top: 2px;">Ongoing website maintenance and updates</div>
                                        </td>
                                        <td style="padding: 16px 0; text-align: center; color: #111827; border-bottom: 1px solid #f3f4f6;">3</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6;">$150</td>
                                        <td style="padding: 16px 0; text-align: right; color: #111827; border-bottom: 1px solid #f3f4f6; font-weight: 600;">$450</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <div style="display: flex; justify-content: flex-end; margin-bottom: 40px;">
                            <div style="width: 250px;">
                                <div style="display: flex; justify-content: space-between; padding: 8px 0;">
                                    <span style="color: #6b7280; font-size: 14px;">Subtotal</span>
                                    <span style="color: #111827; font-weight: 500;">$3,750</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 8px 0;">
                                    <span style="color: #6b7280; font-size: 14px;">Tax (8%)</span>
                                    <span style="color: #111827; font-weight: 500;">$300</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 16px 0; border-top: 2px solid #059669; margin-top: 8px;">
                                    <span style="color: #111827; font-weight: 600; font-size: 16px;">Total</span>
                                    <span style="color: #059669; font-weight: 700; font-size: 18px;">$4,050</span>
                                </div>
                            </div>
                        </div>

                        <footer style="text-align: center; color: #6b7280; font-size: 12px; padding-top: 30px; border-top: 1px solid #f3f4f6;">
                            <p>Thank you for choosing sustainable solutions. 🌱</p>
                            <p style="margin-top: 8px;">Payment terms: 30 days. Please include invoice number on payment.</p>
                        </footer>
                    </div>
                ''',
                'tags': ['minimalist', 'green', 'eco', 'modern'],
                'compatible_types': ['invoice', 'quote'],
                'download_count': 650,
                'rating': 4.7,
                'review_count': 45,
            },
            {
                'title': 'Creative Orange',
                'description': 'Bold and creative invoice template with orange accents. Perfect for creative agencies and design studios.',
                'template_type': 'creator',
                'price': 12,
                'demo_html': '''
                    <div style="font-family: 'Montserrat', sans-serif; max-width: 650px; margin: 0 auto; padding: 40px; background: linear-gradient(135deg, #fff8f0 0%, #fef7f0 100%); border-radius: 12px; position: relative; overflow: hidden;">
                        <div style="position: absolute; top: 0; right: 0; width: 150px; height: 150px; background: linear-gradient(135deg, #fb923c 0%, #ea580c 100%); border-radius: 0 0 0 100%; opacity: 0.1;"></div>

                        <header style="position: relative; z-index: 2; margin-bottom: 50px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h1 style="color: #ea580c; font-size: 42px; margin: 0; font-weight: 800; letter-spacing: -2px;">INVOICE</h1>
                                    <div style="width: 60px; height: 4px; background: linear-gradient(90deg, #fb923c 0%, #ea580c 100%); margin-top: 8px; border-radius: 2px;"></div>
                                </div>
                                <div style="text-align: right;">
                                    <h2 style="color: #1f2937; font-size: 20px; margin: 0; font-weight: 700;">Creative Studio</h2>
                                    <p style="color: #6b7280; margin: 5px 0 0 0; font-size: 14px;">123 Design Street<br>Innovation City, IC 12345</p>
                                    <p style="color: #6b7280; margin: 2px 0; font-size: 13px;">✉ hello@creativestudio.com</p>
                                </div>
                            </div>
                        </header>

                        <div style="position: relative; z-index: 2; margin-bottom: 50px;">
                            <div style="background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(234, 88, 12, 0.1); border: 1px solid rgba(251, 146, 60, 0.2);">
                                <div style="display: flex; justify-content: space-between; align-items: start;">
                                    <div style="flex: 1;">
                                        <h3 style="color: #ea580c; font-size: 16px; margin: 0 0 15px 0; font-weight: 700;">🎯 CLIENT</h3>
                                        <h4 style="color: #1f2937; font-size: 18px; margin: 0 0 8px 0; font-weight: 600;">Awesome Client Co.</h4>
                                        <p style="color: #6b7280; margin: 0; line-height: 1.5;">456 Innovation Drive<br>Tech Valley, TV 67890<br>📞 (555) 123-4567</p>
                                    </div>
                                    <div style="flex: 1; text-align: right;">
                                        <div style="background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); padding: 15px; border-radius: 8px; display: inline-block;">
                                            <div style="margin-bottom: 10px;">
                                                <span style="color: #92400e; font-size: 12px; font-weight: 600; text-transform: uppercase;">Invoice #</span>
                                                <span style="color: #1f2937; font-size: 16px; font-weight: 700; margin-left: 8px;">CS-2024-001</span>
                                            </div>
                                            <div style="margin-bottom: 8px;">
                                                <span style="color: #92400e; font-size: 11px;">DATE:</span>
                                                <span style="color: #1f2937; font-weight: 600; margin-left: 8px;">Jan 15, 2024</span>
                                            </div>
                                            <div>
                                                <span style="color: #92400e; font-size: 11px;">DUE:</span>
                                                <span style="color: #1f2937; font-weight: 600; margin-left: 8px;">Feb 15, 2024</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div style="position: relative; z-index: 2; margin-bottom: 50px;">
                            <table style="width: 100%; border-collapse: separate; border-spacing: 0;">
                                <thead>
                                    <tr>
                                        <th style="background: linear-gradient(135deg, #ea580c 0%, #dc2626 100%); color: white; padding: 18px 20px; text-align: left; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; border-radius: 8px 0 0 8px;">Service</th>
                                        <th style="background: linear-gradient(135deg, #ea580c 0%, #dc2626 100%); color: white; padding: 18px 20px; text-align: center; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">Hours</th>
                                        <th style="background: linear-gradient(135deg, #ea580c 0%, #dc2626 100%); color: white; padding: 18px 20px; text-align: right; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; border-radius: 0 8px 8px 0;">Total</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr style="background: white; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);">
                                        <td style="padding: 20px; border-radius: 8px 0 0 8px;">
                                            <div style="font-weight: 600; color: #1f2937; margin-bottom: 4px;">Brand Identity Design</div>
                                            <div style="color: #6b7280; font-size: 13px;">Logo, color palette, typography, brand guidelines</div>
                                        </td>
                                        <td style="padding: 20px; text-align: center; font-weight: 600; color: #1f2937;">24</td>
                                        <td style="padding: 20px; text-align: right; font-weight: 700; color: #ea580c; font-size: 16px;">$2,400</td>
                                    </tr>
                                    <tr style="background: white; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05); margin-top: 8px;">
                                        <td style="padding: 20px; border-radius: 8px 0 0 8px;">
                                            <div style="font-weight: 600; color: #1f2937; margin-bottom: 4px;">Website Design</div>
                                            <div style="color: #6b7280; font-size: 13px;">UI/UX design for responsive website</div>
                                        </td>
                                        <td style="padding: 20px; text-align: center; font-weight: 600; color: #1f2937;">32</td>
                                        <td style="padding: 20px; text-align: right; font-weight: 700; color: #ea580c; font-size: 16px;">$3,200</td>
                                    </tr>
                                    <tr style="background: white; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05); margin-top: 8px;">
                                        <td style="padding: 20px; border-radius: 8px 0 0 8px;">
                                            <div style="font-weight: 600; color: #1f2937; margin-bottom: 4px;">Content Creation</div>
                                            <div style="color: #6b7280; font-size: 13px;">Copywriting and visual content for website</div>
                                        </td>
                                        <td style="padding: 20px; text-align: center; font-weight: 600; color: #1f2937;">16</td>
                                        <td style="padding: 20px; text-align: right; font-weight: 700; color: #ea580c; font-size: 16px;">$1,600</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <div style="position: relative; z-index: 2;">
                            <div style="display: flex; justify-content: flex-end;">
                                <div style="width: 300px; background: white; padding: 25px; border-radius: 12px; box-shadow: 0 8px 25px rgba(234, 88, 12, 0.15);">
                                    <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f3f4f6;">
                                        <span style="color: #6b7280; font-weight: 500;">Subtotal</span>
                                        <span style="color: #1f2937; font-weight: 600;">$7,200</span>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid #f3f4f6;">
                                        <span style="color: #6b7280; font-weight: 500;">Tax (10%)</span>
                                        <span style="color: #1f2937; font-weight: 600;">$720</span>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; padding: 20px 0 0 0; margin-top: 15px; border-top: 3px solid #ea580c;">
                                        <span style="color: #1f2937; font-weight: 700; font-size: 18px;">TOTAL</span>
                                        <span style="color: #ea580c; font-weight: 800; font-size: 24px;">$7,920</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <footer style="position: relative; z-index: 2; text-align: center; margin-top: 50px; padding-top: 30px; border-top: 1px solid rgba(251, 146, 60, 0.3);">
                            <p style="color: #6b7280; font-size: 14px; margin: 0;">🚀 Thank you for choosing Creative Studio!</p>
                            <p style="color: #9ca3af; font-size: 12px; margin: 8px 0 0 0;">Questions? Reach out to us anytime. Payment due within 30 days.</p>
                        </footer>
                    </div>
                ''',
                'tags': ['creative', 'orange', 'bold', 'agency'],
                'compatible_types': ['invoice', 'quote'],
                'download_count': 320,
                'rating': 4.9,
                'review_count': 28,
            },
            {
                'title': 'Premium Black & Gold',
                'description': 'Luxury invoice template with black and gold styling. Perfect for high-end services and premium brands.',
                'template_type': 'creator',
                'price': 25,
                'demo_html': '''
                    <div style="font-family: 'Playfair Display', serif; max-width: 700px; margin: 0 auto; padding: 60px; background: linear-gradient(145deg, #1f2937 0%, #111827 100%); color: white; border-radius: 16px; position: relative; box-shadow: 0 25px 50px rgba(0, 0, 0, 0.3);">
                        <div style="position: absolute; top: 0; left: 0; right: 0; height: 8px; background: linear-gradient(90deg, #fbbf24 0%, #f59e0b 25%, #d97706 50%, #b45309 75%, #92400e 100%); border-radius: 16px 16px 0 0;"></div>

                        <header style="text-align: center; margin-bottom: 60px; position: relative;">
                            <div style="width: 80px; height: 80px; background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; box-shadow: 0 8px 20px rgba(245, 158, 11, 0.3);">
                                <span style="font-size: 28px; font-weight: 900; color: #1f2937;">$</span>
                            </div>
                            <h1 style="color: #fbbf24; font-size: 48px; margin: 0; font-weight: 900; letter-spacing: -3px; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);">INVOICE</h1>
                            <p style="color: #9ca3af; margin: 10px 0 0 0; font-size: 16px; font-weight: 300;">Premium Services Invoice</p>
                        </header>

                        <div style="display: flex; justify-content: space-between; margin-bottom: 50px;">
                            <div style="flex: 1; background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 12px; border: 1px solid rgba(251, 191, 36, 0.2);">
                                <h3 style="color: #fbbf24; font-size: 14px; margin: 0 0 15px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">From</h3>
                                <h4 style="color: white; font-size: 18px; margin: 0 0 10px 0; font-weight: 600;">Luxury Brand Co.</h4>
                                <div style="color: #d1d5db; line-height: 1.6; font-size: 14px;">
                                    123 Prestige Avenue<br>
                                    Elite City, EC 12345<br>
                                    📞 (555) 999-0000<br>
                                    ✉ premium@luxurybrand.com
                                </div>
                            </div>
                            <div style="width: 40px;"></div>
                            <div style="flex: 1; background: rgba(255, 255, 255, 0.05); padding: 25px; border-radius: 12px; border: 1px solid rgba(251, 191, 36, 0.2);">
                                <h3 style="color: #fbbf24; font-size: 14px; margin: 0 0 15px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">To</h3>
                                <h4 style="color: white; font-size: 18px; margin: 0 0 10px 0; font-weight: 600;">VIP Client Ltd.</h4>
                                <div style="color: #d1d5db; line-height: 1.6; font-size: 14px;">
                                    456 Exclusive Boulevard<br>
                                    Premium District, PD 67890<br>
                                    📞 (555) 111-2222
                                </div>
                            </div>
                        </div>

                        <div style="background: rgba(255, 255, 255, 0.05); padding: 30px; border-radius: 12px; margin-bottom: 50px; border: 1px solid rgba(251, 191, 36, 0.2);">
                            <div style="display: flex; justify-content: space-around; text-align: center;">
                                <div>
                                    <h4 style="color: #fbbf24; font-size: 12px; margin: 0 0 8px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">Invoice #</h4>
                                    <p style="color: white; font-size: 18px; margin: 0; font-weight: 600;">LB-2024-001</p>
                                </div>
                                <div style="width: 1px; height: 40px; background: rgba(251, 191, 36, 0.3);"></div>
                                <div>
                                    <h4 style="color: #fbbf24; font-size: 12px; margin: 0 0 8px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">Date</h4>
                                    <p style="color: white; font-size: 18px; margin: 0; font-weight: 600;">Jan 15, 2024</p>
                                </div>
                                <div style="width: 1px; height: 40px; background: rgba(251, 191, 36, 0.3);"></div>
                                <div>
                                    <h4 style="color: #fbbf24; font-size: 12px; margin: 0 0 8px 0; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">Due Date</h4>
                                    <p style="color: white; font-size: 18px; margin: 0; font-weight: 600;">Feb 15, 2024</p>
                                </div>
                            </div>
                        </div>

                        <div style="margin-bottom: 50px;">
                            <table style="width: 100%; border-collapse: separate; border-spacing: 0 8px;">
                                <thead>
                                    <tr>
                                        <th style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: #1f2937; padding: 20px; text-align: left; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; border-radius: 8px 0 0 8px;">Service Description</th>
                                        <th style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: #1f2937; padding: 20px; text-align: center; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">Qty</th>
                                        <th style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: #1f2937; padding: 20px; text-align: right; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px;">Rate</th>
                                        <th style="background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 100%); color: #1f2937; padding: 20px; text-align: right; font-weight: 700; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; border-radius: 0 8px 8px 0;">Amount</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr style="background: rgba(255, 255, 255, 0.05); border-radius: 8px; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);">
                                        <td style="padding: 25px; border-radius: 8px 0 0 8px;">
                                            <div style="color: white; font-weight: 600; margin-bottom: 5px;">Premium Consulting Package</div>
                                            <div style="color: #9ca3af; font-size: 13px;">Strategic business consulting and premium advisory services</div>
                                        </td>
                                        <td style="padding: 25px; text-align: center; color: white; font-weight: 600;">1</td>
                                        <td style="padding: 25px; text-align: right; color: #fbbf24; font-weight: 700;">$5,000</td>
                                        <td style="padding: 25px; text-align: right; color: #fbbf24; font-weight: 700; font-size: 18px;">$5,000</td>
                                    </tr>
                                    <tr style="background: rgba(255, 255, 255, 0.05); border-radius: 8px; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2); margin-top: 8px;">
                                        <td style="padding: 25px; border-radius: 8px 0 0 8px;">
                                            <div style="color: white; font-weight: 600; margin-bottom: 5px;">Executive Strategy Session</div>
                                            <div style="color: #9ca3af; font-size: 13px;">Private executive coaching and strategic planning</div>
                                        </td>
                                        <td style="padding: 25px; text-align: center; color: white; font-weight: 600;">3</td>
                                        <td style="padding: 25px; text-align: right; color: #fbbf24; font-weight: 700;">$2,500</td>
                                        <td style="padding: 25px; text-align: right; color: #fbbf24; font-weight: 700; font-size: 18px;">$7,500</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <div style="display: flex; justify-content: flex-end; margin-bottom: 50px;">
                            <div style="width: 350px; background: rgba(255, 255, 255, 0.05); padding: 30px; border-radius: 12px; border: 1px solid rgba(251, 191, 36, 0.2);">
                                <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(251, 191, 36, 0.2);">
                                    <span style="color: #d1d5db; font-weight: 500;">Subtotal</span>
                                    <span style="color: white; font-weight: 600;">$12,500</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid rgba(251, 191, 36, 0.2);">
                                    <span style="color: #d1d5db; font-weight: 500;">Service Fee (15%)</span>
                                    <span style="color: white; font-weight: 600;">$1,875</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; padding: 20px 0 0 0; margin-top: 20px; border-top: 2px solid #fbbf24;">
                                    <span style="color: white; font-weight: 700; font-size: 20px;">TOTAL DUE</span>
                                    <span style="color: #fbbf24; font-weight: 900; font-size: 28px;">$14,375</span>
                                </div>
                            </div>
                        </div>

                        <footer style="text-align: center; padding-top: 40px; border-top: 1px solid rgba(251, 191, 36, 0.2);">
                            <p style="color: #d1d5db; font-size: 16px; margin: 0; font-weight: 300;">"Excellence in Every Detail"</p>
                            <p style="color: #9ca3af; font-size: 14px; margin: 10px 0 0 0;">Payment terms: 30 days from invoice date. Please reference invoice number on all payments.</p>
                            <p style="color: #9ca3af; font-size: 13px; margin: 8px 0 0 0;">For questions, contact our premium concierge at concierge@luxurybrand.com</p>
                        </footer>
                    </div>
                ''',
                'tags': ['premium', 'luxury', 'gold', 'black'],
                'compatible_types': ['invoice', 'quote'],
                'download_count': 180,
                'rating': 5.0,
                'review_count': 12,
            }
        ]

        # Create templates
        for template_data in templates_data:
            template, created = MarketplaceTemplate.objects.get_or_create(
                slug=slugify(template_data['title']),
                defaults={
                    'title': template_data['title'],
                    'description': template_data['description'],
                    'template_type': template_data['template_type'],
                    'price': template_data['price'],
                    'demo_html': template_data['demo_html'],
                    'tags': template_data['tags'],
                    'compatible_types': template_data['compatible_types'],
                    'download_count': template_data['download_count'],
                    'rating': template_data['rating'],
                    'review_count': template_data['review_count'],
                    # Default template content for system templates
                    'html_structure': '<div class="invoice">{{ invoice.content }}</div>',
                    'css_styles': '.invoice { font-family: Arial, sans-serif; }',
                    'layout_config': {},
                    'style_config': {},
                }
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(f'Created template: {template.title} ({template.price} {template.currency})')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Template already exists: {template.title}')
                )

        # Create some sample reviews
        self.stdout.write('Creating sample reviews...')

        # Get some users (if they exist)
        users = User.objects.filter(is_active=True)[:3]  # Get first 3 active users
        templates = MarketplaceTemplate.objects.all()[:3]  # Get first 3 templates

        review_texts = [
            "Excellent template! Very professional and easy to customize.",
            "Love the design, works perfectly for my business invoices.",
            "Great value for money. Highly recommend this template.",
            "Beautiful design and very user-friendly. Five stars!",
            "Perfect for my creative agency. Clients love the look.",
        ]

        for i, template in enumerate(templates):
            for j, user in enumerate(users):
                if i + j < len(review_texts):  # Avoid index errors
                    review, created = TemplateReview.objects.get_or_create(
                        user=user,
                        template=template,
                        defaults={
                            'rating': 5 if j % 2 == 0 else 4,
                            'comment': review_texts[i + j],
                            'is_verified_purchase': True,
                        }
                    )
                    if created:
                        # Update template rating
                        template.update_rating()

        self.stdout.write(
            self.style.SUCCESS('Successfully populated marketplace with sample templates and reviews')
        )
