-- Demo dataset (spec §9): normalized authors/books + a denormalized view (v1's flat
-- execution surface). SOURCE OF TRUTH for demo data; gateway/demo/rows.py mirrors it.
DROP VIEW IF EXISTS books_view;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS authors;

CREATE TABLE authors (
    author_id   integer PRIMARY KEY,
    author_name text NOT NULL,
    birth_year  integer,
    country     text
);
COMMENT ON COLUMN authors.author_name IS 'full name of the person who wrote the book';
COMMENT ON COLUMN authors.birth_year  IS 'year the author was born';
COMMENT ON COLUMN authors.country     IS 'author''s country of origin';

CREATE TABLE books (
    book_id      integer PRIMARY KEY,
    title        text NOT NULL,
    category     text,
    published_at date,
    price        numeric(8,2),
    page_count   integer,
    language     text,
    author_id    integer REFERENCES authors(author_id)
);
COMMENT ON COLUMN books.title        IS 'the title of the book';
COMMENT ON COLUMN books.category     IS 'genre / subject classification';
COMMENT ON COLUMN books.published_at IS 'date the book was published';
COMMENT ON COLUMN books.price        IS 'retail price in USD';
COMMENT ON COLUMN books.page_count   IS 'number of pages';
COMMENT ON COLUMN books.language     IS 'language the book is written in';

INSERT INTO authors (author_id, author_name, birth_year, country) VALUES
    (1, 'Ursula K. Le Guin', 1929, 'USA'),
    (2, 'SansWord',          1985, 'USA'),
    (3, 'R. Novak',          1970, 'UK'),
    (4, 'Old Writer',        1940, 'France'),
    (5, 'A. Blake',          1960, 'UK'),
    (6, 'M. Ito',            1988, 'Japan');

INSERT INTO books (book_id, title, category, published_at, price, page_count, language, author_id) VALUES
    (1, 'A Wizard of Earthsea', 'Fantasy',         '1968-01-01',  9.99, 205, 'en', 1),
    (2, 'Future Shock 2026',    'Science Fiction', '2026-03-01', 15.00, 350, 'en', 2),
    (3, 'The Long Orbit',       'Science Fiction', '2026-05-10', 24.00, 500, 'en', 3),
    (4, 'Vieux Roman',          'Non-Fiction',     '2010-01-01', 12.00, 280, 'fr', 4),
    (5, 'Orbit of Dreams',      'Science Fiction', '2025-11-20', 30.00, 420, 'en', 5),
    (6, 'Silent Fields',        'Non-Fiction',     '2026-01-15', 18.50, 300, 'en', 6);

CREATE VIEW books_view AS
    SELECT b.book_id, b.title, b.category, b.published_at, b.price, b.page_count,
           b.language, a.author_id, a.author_name, a.birth_year, a.country
    FROM books b JOIN authors a ON a.author_id = b.author_id;

-- Comment the VIEW columns directly: a view does not inherit its base tables'
-- column comments, and describe() introspects the view. These descriptions are
-- what the resolver sees (they mirror gateway/demo/rows.py's VIEW_FIELDS).
COMMENT ON COLUMN books_view.book_id      IS 'primary key of the book record';
COMMENT ON COLUMN books_view.title        IS 'the title of the book';
COMMENT ON COLUMN books_view.category     IS 'genre / subject classification';
COMMENT ON COLUMN books_view.published_at IS 'date the book was published';
COMMENT ON COLUMN books_view.price        IS 'retail price in USD';
COMMENT ON COLUMN books_view.page_count   IS 'number of pages';
COMMENT ON COLUMN books_view.language     IS 'language the book is written in';
COMMENT ON COLUMN books_view.author_id    IS 'primary key of the author record';
COMMENT ON COLUMN books_view.author_name  IS 'full name of the person who wrote the book';
COMMENT ON COLUMN books_view.birth_year   IS 'year the author was born';
COMMENT ON COLUMN books_view.country      IS 'author''s country of origin';
