"""REDE-69: map the server's millisecond tick onto the local monotonic clock."""


class ServerClock:
    SAMPLES = 20

    def __init__(self):
        self.request_at = None
        self.samples = []  # (round trip, offset) from time requests answered by 007F
        self.fallback = None  # min(local receive - server tick): biased by one-way latency

    def request_sent(self, now):
        self.request_at = now

    def time_reply(self, tick, now):
        if self.request_at is not None and 0 <= now-self.request_at <= 5:
            rtt = now-self.request_at
            self.samples = (self.samples+[(rtt, now-rtt/2-tick/1000)])[-self.SAMPLES:]
        self.request_at = None
        self.observe(tick, now)

    def observe(self, tick, now):
        offset = now-tick/1000
        if self.fallback is None or offset < self.fallback or offset-self.fallback > 60:
            self.fallback = offset  # also resets on server tick wrap or restart

    @property
    def offset(self):
        if self.samples:
            return min(self.samples)[1]
        return self.fallback

    @property
    def round_trip(self):
        return min(self.samples)[0] if self.samples else None

    def to_local(self, tick, now):
        """Local time of a server tick, never in the future of the packet's arrival."""
        if self.offset is None:
            return now
        return min(now, tick/1000+self.offset)
