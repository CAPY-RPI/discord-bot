-- /ping — success
INSERT INTO telemetry_interactions
    (correlation_id, timestamp, interaction_type, user_id,
     command_name, guild_id, guild_name, channel_id, options, bot_version)
VALUES
    ('a3f9c1d20b4e', NOW() - INTERVAL '5 minutes', 'slash_command',
     123456789012345678, 'ping', 987654321098765432, 'CAPY Server', 111222333444555666, '{}', '0.1.0'),
    -- /profile — success
    ('b7e2d4f81c9a', NOW() - INTERVAL '4 minutes', 'slash_command',
     234567890123456789, 'profile', 987654321098765432, 'CAPY Server', 111222333444555666,
     '{"action": "view"}', '0.1.0'),
    -- button click in a DM (no command_name, no guild)
    ('c1a3b5d7e9f0', NOW() - INTERVAL '3 minutes', 'button',
     345678901234567890, NULL, NULL, NULL, 222333444555666777, '{}', '0.1.0'),
    -- modal submit in a guild
    ('e5f7a9b1c3d2', NOW() - INTERVAL '1 minute', 'modal',
     234567890123456789, NULL, 987654321098765432, 'CAPY Server', 111222333444555666,
     '{"reason": "test feedback"}', '0.1.0');

INSERT INTO telemetry_completions
    (correlation_id, timestamp, command_name, status, duration_ms)
VALUES
    ('a3f9c1d20b4e', NOW() - INTERVAL '5 minutes' + INTERVAL '109 ms',
     'ping', 'success', 109.3),
    ('b7e2d4f81c9a', NOW() - INTERVAL '4 minutes' + INTERVAL '234 ms',
     'profile', 'success', 234.1);

-- /event — internal error
INSERT INTO telemetry_interactions
    (correlation_id, timestamp, interaction_type, user_id,
     command_name, guild_id, guild_name, channel_id, bot_version)
VALUES
    ('d4e6f8a0b2c3', NOW() - INTERVAL '2 minutes', 'slash_command',
     456789012345678901, 'event', 987654321098765432, 'CAPY Server', 111222333444555666, '0.1.0');

INSERT INTO telemetry_completions
    (correlation_id, timestamp, command_name, status, duration_ms, error_type)
VALUES
    ('d4e6f8a0b2c3', NOW() - INTERVAL '2 minutes' + INTERVAL '52 ms',
     'event', 'internal_error', 52.0, 'RuntimeError');
