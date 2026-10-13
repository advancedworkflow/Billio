# Billio - SaaS Invoice Management System

Billio is a comprehensive SaaS platform for invoice creation, management, and payment processing. Built with Django and Django REST Framework, it provides a complete solution for freelancers, small businesses, and agencies to manage their invoicing workflow.

## Features

### Core Functionality
- **Invoice Creation**: Create professional invoices with customizable templates
- **Client Management**: Maintain detailed client information and contact history
- **Payment Processing**: Integrated payment processing with Stripe
- **Quote Generation**: Create and manage quotes/estimates
- **PDF Generation**: Automatic PDF generation for invoices
- **Multi-organization**: Support for multiple organizations per user

### SaaS Features
- **Subscription Management**: Tiered pricing plans (Free, Pro, Business, Enterprise)
- **Usage Tracking**: Monitor invoice creation limits and usage
- **Dashboard Analytics**: Comprehensive reporting and analytics
- **Template System**: Customizable invoice templates with branding

### Technical Features
- **Frontend Stack**: HTMX + Alpine.js + Tailwind CSS for modern, interactive UI
- **REST API**: Complete REST API for all functionality
- **Authentication**: JWT and social login (Google)
- **Background Processing**: Celery for async tasks
- **File Storage**: AWS S3 or local storage for files
- **Email Integration**: SendGrid or SMTP for email delivery

## Project Structure

```
billio/
├── config/                    # Django configuration
│   ├── settings/
│   │   ├── base.py           # Base settings
│   │   ├── dev.py            # Development settings
│   │   └── prod.py           # Production settings
│   ├── urls.py
│   ├── asgi.py
│   ├── wsgi.py
│   └── celery.py
├── apps/                     # Django apps
│   ├── landing/              # Public landing page
│   ├── accounts/             # User management & authentication
│   ├── organizations/        # Multi-organization support
│   ├── clients/              # Client management
│   ├── invoices/             # Invoice & quote management
│   ├── payments/             # Payment processing
│   ├── subscriptions/        # SaaS subscription management
│   ├── dashboard/            # Analytics & reporting
│   └── templates_app/        # Invoice templates
├── templates/                # HTML templates
├── static/                   # Static files (CSS, JS)
├── media/                    # User uploaded files
└── tests/                    # Test suite
```

## Installation

### Prerequisites
- Python 3.9+
- PostgreSQL
- Redis (for Celery)
- Node.js (for frontend, if applicable)

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd billio
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   # For development (includes testing and development tools)
   pip install -r requirements-dev.txt

   # For production (minimal dependencies)
   pip install -r requirements.txt
   ```

4. **Environment configuration**
   ```bash
   cp env.example .env
   # Edit .env with your configuration
   ```

5. **Run setup verification**
   ```bash
   python check_setup.py
   ```

6. **Set up pre-commit hooks (optional)**
   ```bash
   pre-commit install
   ```

5. **Database setup**
   ```bash
   python manage.py migrate
   ```

6. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

7. **Run development server**

   ### 🚀 One-Click Startup (Recommended)
   ```bash
   python start_simple.py
   ```
   - ✅ **Automatic setup**: Applies migrations, creates admin user
   - ✅ **URL**: `http://127.0.0.1:8000`
   - ✅ **Login**: `admin@billio.local` / `admin123`

   ### Alternative Options
   ```bash
   python start_dev.py        # HTTP-only server
   python start_complete.py   # Full setup with dependencies
   python manage.py runserver # Basic Django server
   ```

   ### Manual Setup
   ```bash
   python manage.py migrate          # Apply migrations
   python manage.py createsuperuser  # Create admin user
   python manage.py runserver        # Start server
   ```

## Configuration

### Environment Variables

Key environment variables to configure:

- `SECRET_KEY`: Django secret key
- `DEBUG`: Debug mode (True/False)
- `DATABASE_URL`: Database connection URL
- `REDIS_URL`: Redis connection URL
- `STRIPE_SECRET_KEY`: Stripe secret key for payments
- `EMAIL_HOST_USER`: Email configuration

### Database

The application supports PostgreSQL in production and SQLite for development.

### Email

Configure email settings for invoice delivery:
- SMTP configuration
- SendGrid API
- Amazon SES

### File Storage

Choose between:
- Local file storage (development)
- AWS S3 (production)
- Other cloud storage providers

## Landing Page

The project includes a beautiful, conversion-optimized landing page built with:

- **Modern Design**: Clean, professional aesthetic with gradient text effects
- **Responsive Layout**: Mobile-first design that works on all devices
- **Interactive Elements**: Smooth animations and hover effects
- **Conversion Focused**: Clear value proposition, social proof, and CTAs
- **SEO Optimized**: Proper meta tags and semantic HTML structure

### Features
- Hero section with invoice preview
- Problem/solution framework
- Feature showcase with icons
- Pricing comparison table
- FAQ section with expandable answers
- Social proof and testimonials
- Security and trust indicators

## Dependencies

### Core Dependencies (`requirements.txt`)

#### Django Ecosystem
- **Django 4.2.7**: Web framework core
- **Django REST Framework 3.14.0**: API development
- **django-cors-headers**: Cross-origin resource sharing

#### Database & Storage
- **psycopg2-binary**: PostgreSQL adapter
- **django-storages**: Cloud storage support
- **boto3**: AWS S3 integration
- **Pillow**: Image processing

#### Authentication & Security
- **django-allauth**: Social authentication
- **djangorestframework-simplejwt**: JWT tokens
- **bcrypt**: Password hashing

#### Payments & Business Logic
- **stripe**: Payment processing
- **reportlab**: PDF generation
- **weasyprint**: Advanced PDF rendering

#### Background Processing
- **celery**: Task queue
- **redis**: Message broker and cache
- **django-celery-beat**: Periodic tasks
- **django-celery-results**: Task results storage

#### Communication
- **sendgrid**: Email delivery
- **requests**: HTTP client

#### Utilities
- **python-dotenv**: Environment variables
- **python-dateutil**: Date/time utilities
- **django-phonenumber-field**: Phone number validation

### Development Dependencies (`requirements-dev.txt`)

#### Testing
- **pytest & pytest-django**: Testing framework
- **factory-boy**: Test data generation
- **faker**: Fake data generation

#### Code Quality
- **black**: Code formatting
- **flake8**: Linting
- **isort**: Import sorting
- **mypy**: Type checking
- **pre-commit**: Git hooks

#### Development Tools
- **django-debug-toolbar**: Debug information
- **django-extensions**: Additional management commands
- **django-admin-interface**: Enhanced admin interface

#### Documentation
- **sphinx**: Documentation generation
- **drf-spectacular**: API documentation

#### Deployment
- **gunicorn**: WSGI server
- **whitenoise**: Static file serving

### Optional Dependencies

#### Monitoring & Observability
- **sentry-sdk**: Error tracking
- **structlog**: Structured logging

#### API Features
- **django-ratelimit**: Rate limiting
- **django-redis**: Redis caching

### Managing Dependencies

#### Adding New Dependencies
```bash
# Add to requirements.txt for production dependencies
# Add to requirements-dev.txt for development dependencies

# Update your environment
pip install -r requirements-dev.txt
```

#### Updating Dependencies
```bash
# Check for outdated packages
pip list --outdated

# Update specific package
pip install --upgrade package-name

# Update all packages (be careful!)
pip install --upgrade -r requirements-dev.txt
```

#### Development vs Production
- Use `requirements-dev.txt` for local development
- Use `requirements.txt` for production deployment
- Development includes testing, debugging, and code quality tools

#### Django Debug Toolbar
When in DEBUG mode, Django Debug Toolbar is automatically enabled:

- **Access**: Visit any page in your browser
- **Features**: SQL queries, template rendering, cache hits, signals
- **URL**: `__debug__/`
- **Configuration**: Automatically configured for `127.0.0.1`, `localhost`

Make sure your browser's IP is in `INTERNAL_IPS` in settings.

For troubleshooting, see: `docs/debug_toolbar_troubleshooting.md`

## Code Quality

### Pre-commit Hooks
```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run hooks manually
pre-commit run --all-files

# Update hooks
pre-commit autoupdate
```

### Code Formatting & Linting
```bash
# Format code
black .

# Sort imports
isort .

# Lint code
flake8 .

# Type checking
mypy .

# Security checks
bandit -r .
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=apps --cov=config

# Run specific test
pytest apps/accounts/tests/test_models.py

# Run API tests
pytest -m api
```

## Frontend Stack

Billio uses a modern, lightweight frontend stack focused on developer experience and performance:

### HTMX
- **Server-driven UI**: No complex frontend frameworks
- **Progressive Enhancement**: Works without JavaScript
- **Simple Interactions**: AJAX requests without custom JavaScript
- **Small Footprint**: ~10kb minified

### Alpine.js
- **Reactive Components**: Lightweight Vue.js alternative
- **Declarative Syntax**: HTML-based component logic
- **No Build Step**: Works directly in the browser
- **Scoped State**: Component-level state management

### Tailwind CSS
- **Utility-First**: Rapid UI development
- **Responsive Design**: Mobile-first approach
- **Customizable**: Easy theme customization
- **Performance**: Optimized CSS output

### Key Features
- **Dynamic Interactions**: Real-time updates without page reloads
- **Form Handling**: AJAX form submissions with validation
- **Modal Management**: Dynamic modal dialogs
- **Notifications**: Toast-style notifications
- **Loading States**: Automatic loading indicators

### Example Usage
```html
<!-- HTMX for dynamic content loading -->
<div hx-get="/api/invoices/" hx-trigger="load" hx-swap="innerHTML">
    Loading invoices...
</div>

<!-- Alpine.js for reactive components -->
<div x-data="{ open: false }">
    <button @click="open = !open">Toggle</button>
    <div x-show="open" x-transition>Content</div>
</div>

<!-- Tailwind for styling -->
<button class="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded">
    Button
</button>
```

## API Documentation

### Authentication
- POST `/api/accounts/auth/login/` - User login
- POST `/api/accounts/auth/register/` - User registration
- POST `/api/accounts/auth/logout/` - User logout

### Invoices
- GET `/api/invoices/invoices/` - List invoices
- POST `/api/invoices/invoices/` - Create invoice
- GET `/api/invoices/invoices/{id}/` - Get invoice details
- PUT `/api/invoices/invoices/{id}/` - Update invoice

### Organizations
- GET `/api/organizations/organizations/` - List organizations
- POST `/api/organizations/organizations/` - Create organization

### Clients
- GET `/api/clients/clients/` - List clients
- POST `/api/clients/clients/` - Create client

## Development

### Running Tests
```bash
python manage.py test
```

### Code Quality
```bash
black .                    # Format code
isort .                    # Sort imports
flake8 .                   # Lint code
```

### Celery Workers
```bash
celery -A config worker -l info
celery -A config beat -l info
```

## Deployment

### Docker
```bash
docker-compose up -d
```

### Production Checklist
- [ ] Set `DEBUG=False`
- [ ] Configure production database
- [ ] Set up proper logging
- [ ] Configure static files serving
- [ ] Set up monitoring
- [ ] Configure backups
- [ ] Set up SSL certificates

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For support, please contact [support email] or create an issue in the repository.
