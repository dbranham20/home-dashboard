CREATE TABLE IF NOT EXISTS public.calendar_events (
    id            BIGSERIAL PRIMARY KEY,
    event_date    date        NOT NULL,
    event_time    time        NULL,
    title         text        NOT NULL,
    author        text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_event_date ON calendar_events (event_date);
CREATE INDEX IF NOT EXISTS idx_calendar_events_event_date_time ON calendar_events (event_date, event_time);
CREATE INDEX IF NOT EXISTS idx_calendar_events_author ON calendar_events (author);
ALTER TABLE calendar_events
ADD CONSTRAINT uq_calendar_events_four
UNIQUE (event_date, event_time, title, author);

