# 🚀 Démarrage Rapide - Billio

## Configuration et Lancement

### Option 1: Démarrage Complet (Recommandé)

Lancez ce script pour tout configurer automatiquement :

```bash
python start_with_data.py
```

Ce script va :
1. ✅ Appliquer toutes les migrations de base de données
2. ✅ Créer des données de test complètes
3. ✅ Lancer le serveur de développement

### Option 2: Démarrage Manuel

Si vous préférez configurer étape par étape :

```bash
# 1. Appliquer les migrations
python manage.py migrate

# 2. Créer les données de test
python manage.py populate_db

# 3. Lancer le serveur
python manage.py runserver
```

## 🔑 Comptes de Test

Après le démarrage, vous pouvez vous connecter avec :

- **Admin**: `admin` / `admin123`
- **Test User**: `testuser` / `test123`

## 📊 Données de Test Créées

- **3 Organisations** avec différents types (agency, small_business)
- **12 Clients** (4 par organisation) avec informations complètes
- **6 Templates de factures** (2 par organisation) avec différentes configurations
- **24 Factures** avec statuts variés (draft, sent, paid, overdue)
- **Plus de 70 articles de facture** avec calculs automatiques
- **12 Taxes** configurées (TVA 0%, 5.5%, 10%, 20%)

## 🌐 Accès à l'Application

Une fois lancé, accédez à :
- **Dashboard**: http://127.0.0.1:8000/dashboard/
- **Factures**: http://127.0.0.1:8000/invoices/list/
- **Clients**: http://127.0.0.1:8000/clients/list/
- **Création de facture**: http://127.0.0.1:8000/invoices/create/

## ✨ Fonctionnalités Disponibles

- ✅ Interface moderne et responsive
- ✅ Sidebar fixe avec navigation
- ✅ Header avec dropdown de profil
- ✅ Création et édition de factures avec templates
- ✅ Gestion des clients et organisations
- ✅ Prévisualisation en temps réel des factures
- ✅ Export PDF (démonstration)
- ✅ Mode démo pour tester sans inscription

## 🛠️ Développement

Pour les développeurs, le projet utilise :
- **Django** pour le backend
- **Tailwind CSS** pour le styling
- **Alpine.js** pour les interactions JavaScript
- **HTMX** pour les mises à jour dynamiques
- **SQLite** pour la base de données (développement)

## 📝 Notes

- Les données de test sont créées automatiquement et peuvent être supprimées/modifiées
- Le mode démo permet de tester la création de factures sans sauvegarde
- Toutes les fonctionnalités sont opérationnelles avec les données de test


