CREATE TABLE IF NOT EXISTS public."tesla-miles-log"
(
    id integer NOT NULL DEFAULT nextval('"tesla-miles-log_id_seq"'::regclass),
    date date NOT NULL,
    miles integer NOT NULL,
    CONSTRAINT "tesla-miles-log_pkey" PRIMARY KEY (id)
)

TABLESPACE pg_default;

ALTER TABLE public."tesla-miles-log"
    OWNER to postgres;
