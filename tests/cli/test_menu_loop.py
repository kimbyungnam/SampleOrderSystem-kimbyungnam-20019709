from semi.cli.menu_loop import main_loop
from semi.services.exceptions import DomainError
from semi.storage.exceptions import NotFoundError


class _FakeController:
    def __init__(self, label, action=None):
        self.label = label
        self._action = action
        self.run_calls = 0

    def run(self) -> None:
        self.run_calls += 1
        if self._action is not None:
            self._action()


def test_main_loop_exits_immediately_when_render_returns_exit():
    controller = _FakeController("시료 관리")

    main_loop([controller], render_main_menu=lambda labels: "exit")

    assert controller.run_calls == 0


def test_main_loop_dispatches_to_selected_controller_then_exits():
    controller_a = _FakeController("시료 관리")
    controller_b = _FakeController("주문 접수")
    choices = iter([1, "exit"])

    main_loop(
        [controller_a, controller_b], render_main_menu=lambda labels: next(choices)
    )

    assert controller_a.run_calls == 0
    assert controller_b.run_calls == 1


def test_main_loop_passes_controller_labels_to_render_main_menu():
    controller_a = _FakeController("시료 관리")
    controller_b = _FakeController("주문 접수")
    seen_labels = []

    def render(labels):
        seen_labels.append(list(labels))
        return "exit"

    main_loop([controller_a, controller_b], render_main_menu=render)

    assert seen_labels == [["시료 관리", "주문 접수"]]


def test_main_loop_catches_domain_error_and_continues(capsys):
    def raise_domain_error():
        raise DomainError("bad quantity")

    controller = _FakeController("주문 접수", action=raise_domain_error)
    choices = iter([0, "exit"])

    main_loop([controller], render_main_menu=lambda labels: next(choices))

    assert controller.run_calls == 1
    assert "[오류] bad quantity" in capsys.readouterr().out


def test_main_loop_catches_not_found_error_and_continues(capsys):
    def raise_not_found():
        raise NotFoundError("order_id=99 not found")

    controller = _FakeController("출고 처리", action=raise_not_found)
    choices = iter([0, "exit"])

    main_loop([controller], render_main_menu=lambda labels: next(choices))

    assert controller.run_calls == 1
    assert "[조회 실패] order_id=99 not found" in capsys.readouterr().out
