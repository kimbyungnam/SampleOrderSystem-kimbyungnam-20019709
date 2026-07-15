from semi.cli import views


class SampleMenuController:
    label = "시료 관리"

    def __init__(self, sample_service) -> None:
        self._service = sample_service

    def run(self) -> None:
        while True:
            choice = views.render_sample_menu()
            if choice == "back":
                return
            elif choice == "register":
                data = views.prompt_sample_registration()
                sample = self._service.register(**data)
                views.render_sample_registered(sample)
            elif choice == "list":
                views.render_sample_list(self._service.list_all())
            elif choice == "search":
                query = views.prompt_search_query()
                views.render_sample_list(self._service.search_by_name(query))
