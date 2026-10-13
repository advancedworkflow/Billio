# 🔒 HTTP-Only Development Setup

## SSL Protocol Error Fix

If you see `ERR_SSL_PROTOCOL_ERROR` when accessing the development server, follow these steps:

### 🚀 Quick Start (HTTP Only)

```bash
# 1. Navigate to billio directory
cd billio

# 2. Start the HTTP-only server
python start_dev.py
```

### 📍 Access the Application

**IMPORTANT**: Always use HTTP, never HTTPS in development:

✅ **Correct**: `http://127.0.0.1:8000`
❌ **Wrong**: `https://127.0.0.1:8000`

### 🔧 Troubleshooting SSL Errors

If you still get SSL errors:

1. **Clear browser cache and cookies** for 127.0.0.1
2. **Hard refresh**: Ctrl+F5 or Cmd+Shift+R
3. **Try incognito/private browsing mode**
4. **Check browser address bar** - ensure it's `http://`, not `https://`

### 🛠️ Manual Server Start

If the script doesn't work:

```bash
# Set environment to force HTTP
set wsgi.url_scheme=http
set HTTPS=off

# Start server
python manage.py runserver --noreload --insecure 127.0.0.1:8000
```

### ⚙️ Configuration

The development server is configured to:
- ✅ Force HTTP protocol
- ✅ Disable SSL redirects
- ✅ Handle HTTPS requests gracefully
- ✅ Prevent HSTS headers

### 🔐 Production vs Development

- **Development**: HTTP only, no SSL
- **Production**: HTTPS required, SSL certificates needed

### 📞 Need Help?

If you continue to have SSL issues:
1. Check that no other server is running on port 8000
2. Try a different port: `python manage.py runserver 127.0.0.1:8001`
3. Clear all browser data for localhost/127.0.0.1


