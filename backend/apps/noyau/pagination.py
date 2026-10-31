from rest_framework.pagination import PageNumberPagination


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "taille"
    max_page_size = 500
