-- 天羽传奇分析库。只建表，不写入任何地图坐标或任务推测。
-- 适用 MySQL 5.7 及以上。来源列不允许为空。

CREATE TABLE IF NOT EXISTS maps (
    map_id VARCHAR(64) NOT NULL,
    map_name VARCHAR(255) NULL,
    map_type VARCHAR(64) NULL,
    width INT NULL,
    height INT NULL,
    npc_list JSON NULL,
    connection_list JSON NULL,
    source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (map_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS npcs (
    npc_id VARCHAR(64) NOT NULL,
    npc_name VARCHAR(255) NULL,
    map_id VARCHAR(64) NULL,
    position_x INT NULL,
    position_y INT NULL,
    npc_type VARCHAR(64) NULL,
    related_quest VARCHAR(64) NULL,
    source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (npc_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quests (
    quest_id VARCHAR(64) NOT NULL,
    quest_name VARCHAR(255) NOT NULL,
    guide_article_id INT NULL,
    min_level INT NULL,
    objective TEXT NULL,
    start_npc VARCHAR(255) NULL,
    target_npc VARCHAR(255) NULL,
    target_map VARCHAR(255) NULL,
    required_items JSON NULL,
    reward_text TEXT NULL,
    reward_items JSON NULL,
    completion_condition TEXT NULL,
    prerequisite_name VARCHAR(255) NULL,
    next_quest_name VARCHAR(255) NULL,
    description TEXT NULL,
    source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    confirmed_absent JSON NULL,
    unconfirmed_fields JSON NULL,
    conflicts JSON NULL,
    duplicate_of VARCHAR(64) NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (quest_id),
    KEY idx_quests_name (quest_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quest_steps (
    step_id BIGINT NOT NULL AUTO_INCREMENT,
    quest_id VARCHAR(64) NOT NULL,
    step_order INT NOT NULL,
    step_type VARCHAR(32) NOT NULL,
    content TEXT NULL,
    target_npc VARCHAR(255) NULL,
    target_map VARCHAR(255) NULL,
    required_items JSON NULL,
    source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    PRIMARY KEY (step_id),
    KEY idx_quest_steps_quest (quest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS map_connections (
    connection_id VARCHAR(64) NOT NULL,
    from_map_id VARCHAR(64) NOT NULL,
    to_map_id VARCHAR(64) NOT NULL,
    source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    note VARCHAR(512) NULL,
    PRIMARY KEY (connection_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_observations (
    observation_id BIGINT NOT NULL AUTO_INCREMENT,
    player_name VARCHAR(255) NULL,
    map_name VARCHAR(255) NULL,
    player_position VARCHAR(255) NULL,
    hp VARCHAR(64) NULL,
    mp VARCHAR(64) NULL,
    target_name VARCHAR(255) NULL,
    current_quest VARCHAR(255) NULL,
    quest_progress VARCHAR(255) NULL,
    observation_timestamp DATETIME NOT NULL,
    data_source VARCHAR(512) NOT NULL,
    confidence DECIMAL(5, 3) NULL,
    PRIMARY KEY (observation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
