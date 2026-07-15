from semi.cli import views
from semi.domain.models import OrderStatus


def test_order_counts(app_context, mocker):
    app_context.sample_service.register("S1", "Wafer A", 10.0, 0.9)
    app_context.sample_repo.increment_stock("S1", 100)
    app_context.sample_repo.conn.commit()
    app_context.sample_service.register("S2", "Wafer B", 10.0, 0.5)

    reserved_order = app_context.order_service.create_order("S1", "Alice", 1)
    confirmed_order = app_context.order_service.create_order("S1", "Bob", 1)
    app_context.order_service.approve(confirmed_order.order_id)
    producing_order = app_context.order_service.create_order("S2", "Carol", 5)
    app_context.order_service.approve(producing_order.order_id)
    rejected_order = app_context.order_service.create_order("S1", "Dan", 1)
    app_context.order_service.reject(rejected_order.order_id)
    assert reserved_order.status == OrderStatus.RESERVED

    mocker.patch(
        "semi.cli.views.render_monitoring_menu",
        side_effect=["order_counts", "back"],
    )
    render_counts = mocker.patch("semi.cli.views.render_order_counts")

    monitoring_menu_controller = app_context.controllers[2]
    monitoring_menu_controller.run()

    render_counts.assert_called_once_with(
        app_context.monitoring_service.count_by_status()
    )


def test_stock_status_classification(app_context, mocker):
    # SUFFICIENT: stock >= outstanding
    app_context.sample_service.register("SUF", "Sufficient", 10.0, 0.9)
    app_context.sample_repo.increment_stock("SUF", 100)
    app_context.sample_repo.conn.commit()
    app_context.order_service.create_order("SUF", "Alice", 5)

    # SHORT: 0 < stock < outstanding
    app_context.sample_service.register("SHT", "Short", 10.0, 0.9)
    app_context.sample_repo.increment_stock("SHT", 2)
    app_context.sample_repo.conn.commit()
    app_context.order_service.create_order("SHT", "Bob", 5)

    # DEPLETED: stock == 0
    app_context.sample_service.register("DEP", "Depleted", 10.0, 0.9)
    app_context.order_service.create_order("DEP", "Carol", 5)

    mocker.patch(
        "semi.cli.views.render_monitoring_menu",
        side_effect=["stock_status", "back"],
    )
    render_stock_status = mocker.patch("semi.cli.views.render_stock_status")

    monitoring_menu_controller = app_context.controllers[2]
    monitoring_menu_controller.run()

    render_stock_status.assert_called_once_with(
        app_context.monitoring_service.stock_status()
    )


def test_stock_status_korean_labels_rendered(app_context, capsys):
    app_context.sample_service.register("SUF", "Sufficient", 10.0, 0.9)
    app_context.sample_repo.increment_stock("SUF", 100)
    app_context.sample_repo.conn.commit()
    app_context.order_service.create_order("SUF", "Alice", 5)

    app_context.sample_service.register("SHT", "Short", 10.0, 0.9)
    app_context.sample_repo.increment_stock("SHT", 2)
    app_context.sample_repo.conn.commit()
    app_context.order_service.create_order("SHT", "Bob", 5)

    app_context.sample_service.register("DEP", "Depleted", 10.0, 0.9)
    app_context.order_service.create_order("DEP", "Carol", 5)

    views.render_stock_status(app_context.monitoring_service.stock_status())

    out = capsys.readouterr().out
    assert "여유" in out
    assert "부족" in out
    assert "고갈" in out
