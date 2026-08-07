# Documentation architecturale (C4 / Structurizr)

Ce dossier contient le modèle C4 du projet, écrit en [Structurizr DSL](https://docs.structurizr.com/dsl) dans [`workspace.dsl`](workspace.dsl).

Deux niveaux sont documentés (le troisième niveau, Component, n'apporte pas de valeur ici vu la taille du projet — `app.py` et `collector.py` restent chacun un seul container) :

- **Context** : Utilisateur, système Vélo Brussels, API externe `data.mobility.brussels`
- **Container** : Collector (script cron), Base de données (SQLite), Web App (Flask)

Le contenu doit rester synchronisé avec la section "Architecture" du [`CLAUDE.md`](../../CLAUDE.md) et du [`README.md`](../../README.md) à la racine — si l'un change (nouveau container, nouvelle intégration externe), mettre à jour les trois.

## Visualiser le modèle

Un service Structurizr dédié permet de rendre les diagrammes localement, indépendamment du déploiement de l'application elle-même. `structurizr/lite` étant en fin de vie (le conteneur affiche juste un message de dépréciation et s'arrête), ce compose utilise son remplaçant officiel, [`structurizr/structurizr`](https://docs.structurizr.com/local) en mode `local` :

```bash
# Depuis ce dossier (docs/architecture/)
docker compose -f docker-compose.structurizr.yml up
# ou : podman compose -f docker-compose.structurizr.yml up
```

Puis ouvrir [http://localhost:8081](http://localhost:8081) (redirige vers `/workspace/1`).

Arrêter avec `docker compose -f docker-compose.structurizr.yml down` (ou l'équivalent Podman).
