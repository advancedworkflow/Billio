import json

from django.contrib.auth import get_user_model
from django.test import Client as HttpClient, TestCase
from django.urls import reverse

from apps.dashboard.automation_graph import validate_graph
from apps.dashboard.models import AutomationRule
from apps.integrations.recipes import NEEDS, RECIPES
from apps.organizations.models import Organization

TRIGGERS = {k for k, _ in AutomationRule.TRIGGER_CHOICES}
ACTIONS = {k for k, _ in AutomationRule.ACTION_CHOICES}


class RecipesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='r', email='r@test.fr', password='x-Test-1234')
        self.org = Organization.objects.create(name='Studio', owner=self.user)
        self.http = HttpClient(HTTP_HOST='127.0.0.1', HTTP_ACCEPT_LANGUAGE='fr')
        self.http.force_login(self.user)

    def test_every_need_points_to_existing_recipes(self):
        for need in NEEDS:
            for key in need['recipes']:
                self.assertIn(key, RECIPES)

    def test_recipes_without_tool_ids_are_valid_graphs(self):
        # Les recettes sans identifiant à compléter (email, messageries, Drive) s'enregistrent telles quelles.
        for key, recipe in RECIPES.items():
            if any(n['key'] == 'app_action' for n in recipe['graph']['nodes']):
                continue
            validate_graph(recipe['graph'], organization=self.org, valid_triggers=TRIGGERS, valid_actions=ACTIONS)

    def test_integrations_page_shows_needs_and_builder_gets_recipes(self):
        page = self.http.get(reverse('integrations:integrations-page')).content.decode()
        self.assertIn('Que voulez-vous faire ?', page)
        self.assertIn('?recipe=payment-thanks-client', page)
        builder = self.http.get(reverse('dashboard:automation-builder')).content.decode()
        start = builder.index('id="wf-config"')
        config = json.loads(builder[builder.index('>', start) + 1:builder.index('</script>', start)])
        self.assertIn('invoice-drive', config['recipes'])
