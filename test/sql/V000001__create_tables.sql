CREATE TABLE artist (
    artist_id VARCHAR(255) PRIMARY KEY NOT NULL,
    artist_name VARCHAR(255) NOT NULL
);

CREATE TABLE album (
    album_id VARCHAR(255) PRIMARY KEY NOT NULL,
    album_name VARCHAR(255) NOT NULL,
    artist_id VARCHAR(255) NOT NULL,
    release_date DATE,
    CONSTRAINT fk_album_artist FOREIGN KEY (artist_id) REFERENCES artist(artist_id)
);

CREATE TABLE track (
    track_id VARCHAR(255) PRIMARY KEY NOT NULL,
    track_name VARCHAR(255) NOT NULL,
    album_id VARCHAR(255) NOT NULL,
    duration_ms INTEGER,
    track_number INTEGER,
    CONSTRAINT fk_track_album FOREIGN KEY (album_id) REFERENCES album(album_id)
);
