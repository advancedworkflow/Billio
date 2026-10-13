"""
Custom middleware for development server.
"""
import logging

logger = logging.getLogger(__name__)


class HTTPSRedirectMiddleware:
    """
    Middleware to handle HTTPS requests in development.
    Returns a proper error response for HTTPS requests since Django dev server doesn't support SSL.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is an HTTPS request
        if request.META.get('HTTP_X_FORWARDED_PROTO') == 'https' or \
           request.META.get('wsgi.url_scheme') == 'https' or \
           request.META.get('SERVER_PORT') == '443' or \
           request.META.get('HTTPS') == 'on':

            # Log the HTTPS request for debugging
            logger.warning(f"HTTPS request received for {request.path} - redirecting to HTTP")

            # Redirect to HTTP version
            from django.http import HttpResponseRedirect

            # Get the current full path
            current_url = request.build_absolute_uri()

            # Replace https with http
            http_url = current_url.replace('https://', 'http://', 1)

            return HttpResponseRedirect(http_url)

        response = self.get_response(request)
        return response
