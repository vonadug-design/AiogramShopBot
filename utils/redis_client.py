import config

_redis = None


def get_redis():
    """Shared Redis client, created on first use."""
    global _redis
    if _redis is None:
        from redis.asyncio import Redis
        _redis = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD)
    return _redis
