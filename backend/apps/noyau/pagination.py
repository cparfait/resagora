from urllib.parse import urlsplit, urlunsplit

from rest_framework.pagination import PageNumberPagination


def _relatif(url: str | None) -> str | None:
    """Liens de pagination relatifs : jamais le nom interne du serveur (api-portail:8443) vers Internet."""
    if url is None:
        return None
    morceaux = urlsplit(url)
    return urlunsplit(("", "", morceaux.path, morceaux.query, ""))


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "taille"
    max_page_size = 500

    def get_next_link(self) -> str | None:
        return _relatif(super().get_next_link())

    def get_previous_link(self) -> str | None:
        return _relatif(super().get_previous_link())
