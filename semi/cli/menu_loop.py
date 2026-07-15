from typing import Callable, Protocol

from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


class MenuController(Protocol):
    label: str

    def run(self) -> None: ...


def main_loop(
    controllers: list[MenuController],
    render_main_menu: Callable[[list[str]], int | str],
) -> None:
    while True:
        choice = render_main_menu([c.label for c in controllers])
        if choice == "exit":
            break
        try:
            controllers[choice].run()
        except DomainError as e:
            print(f"[오류] {e}")
        except NotFoundError as e:
            print(f"[조회 실패] {e}")
