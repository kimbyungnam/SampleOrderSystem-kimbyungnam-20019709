from enum import StrEnum

from semi.domain.models import JobStatus, OrderStatus


def test_order_status_is_str_enum():
    assert issubclass(OrderStatus, StrEnum)


def test_order_status_members_match_db_check_constraint():
    assert [member.value for member in OrderStatus] == [
        "RESERVED",
        "REJECTED",
        "PRODUCING",
        "CONFIRMED",
        "RELEASE",
    ]


def test_order_status_value_equals_member_name():
    assert OrderStatus.RESERVED.value == "RESERVED"
    assert OrderStatus.CONFIRMED == "CONFIRMED"


def test_job_status_is_str_enum():
    assert issubclass(JobStatus, StrEnum)


def test_job_status_members_match_db_check_constraint():
    assert [member.value for member in JobStatus] == ["QUEUED", "IN_PROGRESS", "DONE"]


def test_job_status_value_equals_member_name():
    assert JobStatus.QUEUED.value == "QUEUED"
    assert JobStatus.DONE == "DONE"
