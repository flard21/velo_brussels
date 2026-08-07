workspace "Vélo Brussels" "Documentation architecturale C4 du projet de collecte des compteurs vélo de Bruxelles" {

    model {
        user = person "Utilisateur" "Consulte le dashboard des compteurs vélo dans son navigateur"

        mobilityApi = softwareSystem "API data.mobility.brussels" "Fournit la liste des dispositifs de comptage vélo et leurs relevés en temps réel" "External"

        veloBrussels = softwareSystem "Vélo Brussels" "Collecte, stocke et affiche l'historique des compteurs vélo de Bruxelles" {
            collector = container "Collector" "Récupère périodiquement la liste des dispositifs et leurs relevés, dédupliqué avant insertion" "Python 3.14, requests, ThreadPoolExecutor — exécuté au démarrage puis via cron toutes les 30 min" "Script"
            database = container "Base de données" "Stocke les dispositifs (devices) et l'historique des relevés (counts)" "SQLite" "Database"
            webapp = container "Web App" "Sert le dashboard (carte Leaflet + graphiques Chart.js) et l'API REST interne" "Python 3.14, Flask" "WebApp"

            collector -> mobilityApi "Récupère la liste des dispositifs et les relevés live" "HTTPS (TLS non vérifié)"
            collector -> database "Insère les nouveaux relevés" "SQL"
            webapp -> database "Lit les dispositifs et l'historique / écrit lors d'un refresh manuel" "SQL"
            webapp -> mobilityApi "Déclenche une collecte à la demande (POST /api/refresh)" "HTTPS (TLS non vérifié)"
            user -> webapp "Consulte le dashboard, déclenche un refresh manuel" "HTTPS"
        }

        user -> veloBrussels "Consulte les données de comptage vélo"
        veloBrussels -> mobilityApi "Récupère les données de comptage" "HTTPS"
    }

    views {
        systemContext veloBrussels "SystemContext" {
            include *
            autoLayout
        }

        container veloBrussels "Containers" {
            include *
            autoLayout
        }

        styles {
            element "Person" {
                shape Person
                background #08427b
                color #ffffff
            }
            element "External" {
                background #999999
                color #ffffff
            }
            element "Software System" {
                background #1168bd
                color #ffffff
            }
            element "WebApp" {
                shape WebBrowser
            }
            element "Database" {
                shape Cylinder
            }
            element "Script" {
                shape Component
            }
        }
    }
}
