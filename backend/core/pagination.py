from rest_framework.pagination import PageNumberPagination


class OpenLIMSPagination(PageNumberPagination):
    """Pagination tuned for interactive LIMS screens.

    Normal list requests return 50 rows, while callers that intentionally need
    a complete collection may request larger pages up to 200 rows. This keeps
    ordinary responses bounded while avoiding the 10-row request chains that
    previously made `apiGetAll()` expensive.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
