CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS tracked_tokens (
        token_address TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        watch_address TEXT NOT NULL,
        name TEXT,
        symbol TEXT,
        telegram_link TEXT,
        chart_link TEXT,
        listing_link TEXT,
        buy_link TEXT,
        post_group INTEGER NOT NULL DEFAULT 1,
        post_channel INTEGER NOT NULL DEFAULT 1,
        is_active INTEGER NOT NULL DEFAULT 1,
        force_trending INTEGER NOT NULL DEFAULT 0,
        force_leaderboard INTEGER NOT NULL DEFAULT 0,
        manual_rank INTEGER,
        trend_until_ts INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS token_settings (
        token_address TEXT PRIMARY KEY,
        buy_step REAL NOT NULL DEFAULT 1,
        min_buy_ton REAL NOT NULL DEFAULT 0,
        emoji TEXT NOT NULL DEFAULT '✅',
        media_file_id TEXT,
        media_kind TEXT NOT NULL DEFAULT 'photo',
        show_media INTEGER NOT NULL DEFAULT 1,
        show_mcap INTEGER NOT NULL DEFAULT 1,
        show_price INTEGER NOT NULL DEFAULT 1,
        show_holders INTEGER NOT NULL DEFAULT 1,
        show_chart INTEGER NOT NULL DEFAULT 1,
        language TEXT NOT NULL DEFAULT 'en',
        FOREIGN KEY(token_address) REFERENCES tracked_tokens(token_address) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS group_settings (
        group_id INTEGER NOT NULL,
        token_address TEXT NOT NULL,
        language TEXT NOT NULL DEFAULT 'en',
        min_buy_ton REAL NOT NULL DEFAULT 0,
        custom_buy_link TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(group_id, token_address),
        FOREIGN KEY(token_address) REFERENCES tracked_tokens(token_address) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_address TEXT,
        text TEXT NOT NULL,
        link TEXT,
        starts_at INTEGER NOT NULL,
        ends_at INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by INTEGER,
        FOREIGN KEY(token_address) REFERENCES tracked_tokens(token_address) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS state_kv (
        k TEXT PRIMARY KEY,
        v TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token_address TEXT,
        kind TEXT NOT NULL,
        duration_key TEXT NOT NULL,
        amount_ton REAL NOT NULL,
        wallet TEXT NOT NULL,
        target_link TEXT,
        ad_text TEXT,
        ad_link TEXT,
        tx_hash TEXT,
        is_paid INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        FOREIGN KEY(token_address) REFERENCES tracked_tokens(token_address) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER PRIMARY KEY,
        language TEXT NOT NULL DEFAULT 'en'
    )
    """
]
