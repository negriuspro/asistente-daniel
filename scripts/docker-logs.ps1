param(
    [string]$Service = ""
)

if ($Service) {
    docker compose --env-file .env logs -f $Service
} else {
    docker compose --env-file .env logs -f
}
