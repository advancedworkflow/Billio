# Django Debug Toolbar Troubleshooting

## Common Issues and Solutions

### Issue: `data-render-panel-url="{% url 'djdt:render_panel' %}"` Error

**Symptoms:**
- Error message containing `data-render-panel-url="{% url 'djdt:render_panel' %}"`
- Debug toolbar not showing in browser
- 404 errors for debug toolbar URLs

**Solutions:**

#### 1. Check Installation
```bash
# Install debug toolbar
pip install django-debug-toolbar

# Or install all dev dependencies
pip install -r requirements-dev.txt
```

#### 2. Verify Configuration
Ensure your settings have:
```python
# In INSTALLED_APPS
'debug_toolbar',

# In MIDDLEWARE (after other middleware)
'debug_toolbar.middleware.DebugToolbarMiddleware',

# In settings
INTERNAL_IPS = [
    '127.0.0.1',
    'localhost',
    '0.0.0.0',
]

DEBUG = True
```

#### 3. Check URLs
Ensure debug toolbar URLs are included:
```python
# In urls.py
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
```

#### 4. Browser IP Configuration
- Your browser's IP must be in `INTERNAL_IPS`
- For local development, `127.0.0.1` usually works
- Check your actual IP: `ifconfig` (Linux/Mac) or `ipconfig` (Windows)

#### 5. Clear Cache
```bash
# Clear Django cache
python manage.py clear_cache

# Or restart your development server
```

### Issue: Debug Toolbar Not Showing

**Check:**
1. `DEBUG = True` in settings
2. Your IP is in `INTERNAL_IPS`
3. No JavaScript errors blocking toolbar
4. Browser developer tools console for errors

### Issue: 404 on Debug URLs

**Check:**
1. Debug toolbar URLs are properly included in main `urls.py`
2. No URL conflicts with your app URLs
3. Server restarted after configuration changes

### Testing Debug Toolbar

Create a simple test view:
```python
from django.http import HttpResponse
from django.shortcuts import render

def test_view(request):
    # This will trigger SQL queries for the toolbar to show
    from apps.accounts.models import User
    users = User.objects.all()[:5]

    context = {
        'users': users,
        'test_data': list(range(100)),  # Create some data
    }
    return render(request, 'test.html', context)
```

### Manual URL Check

You can manually check if debug URLs are working:
```
http://127.0.0.1:8000/__debug__/render_panel/
http://127.0.0.1:8000/__debug__/
```

### Alternative: Use Docker

If you're using Docker, ensure the container IP is in INTERNAL_IPS:
```python
INTERNAL_IPS = [
    '127.0.0.1',
    '172.17.0.1',  # Docker bridge IP
    'host.docker.internal',  # Docker for Mac/Windows
]
```

### Disable Debug Toolbar Temporarily

To disable temporarily, comment out the debug toolbar configuration:
```python
# INSTALLED_APPS.remove('debug_toolbar')
# MIDDLEWARE.remove('debug_toolbar.middleware.DebugToolbarMiddleware')
```


