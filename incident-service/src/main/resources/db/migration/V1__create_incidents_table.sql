CREATE TABLE incidents (
    id               UUID                     PRIMARY KEY,
    title            VARCHAR(255)             NOT NULL,
    description      VARCHAR(2000),
    severity         VARCHAR(20)              NOT NULL,
    status           VARCHAR(20)              NOT NULL,
    affected_service VARCHAR(255)             NOT NULL,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    version          BIGINT                   NOT NULL
);
