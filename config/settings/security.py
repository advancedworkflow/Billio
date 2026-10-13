"""
Security settings for billio project.
This file contains additional security configurations.
"""

# Security middleware settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# HTTPS settings
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie settings
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True

# Content Security Policy (CSP) headers
# Note: This should be implemented with django-csp package for production
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "'unsafe-inline'",
    "'unsafe-eval'",
    "https://cdn.tailwindcss.com",
    "https://unpkg.com",
    "https://unpkg.com/htmx.org",
    "https://unpkg.com/alpinejs",
    "https://cdn.plot.ly",
    "https://cdn.jsdelivr.net",
    "chrome-extension://e9830311-2186-4e8b-b0fb-56a2c30e997e/",
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",
    "https://fonts.googleapis.com",
    "https://cdn.jsdelivr.net",
)
CSP_FONT_SRC = (
    "'self'",
    "https://fonts.gstatic.com",
)
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_CONNECT_SRC = ("'self'", "https://fonts.googleapis.com", "https://fonts.gstatic.com")

# Security headers middleware (consider django-security package)
# SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
# SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

# Rate limiting (consider django-ratelimit package)
# RATELIMIT_RATE = '100/h'
# RATELIMIT_BLOCK = True

# Additional security measures
# - Use django-axes for login attempt monitoring
# - Use django-security for additional headers
# - Regular security audits
# - Monitor for vulnerabilities in dependencies
