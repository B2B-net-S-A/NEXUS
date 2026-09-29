"""Shared pagination limits for list endpoints."""

# Upper bound for the ``page`` query parameter on paginated endpoints.
#
# ``OFFSET`` is computed as ``(page - 1) * page_size`` and bound as a PostgreSQL
# int8. Without an upper bound FastAPI accepts arbitrarily large Python ints, so
# a huge ``page`` overflowed int8 inside asyncpg (NumericValueOutOfRangeError ->
# HTTP 500). With ``page_size`` capped (<= 500 everywhere) this bound keeps the
# offset far inside int8 range and turns absurd input into a 422 instead.
MAX_PAGE = 1_000_000
