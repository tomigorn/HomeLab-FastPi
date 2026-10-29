-- Seerr owner transfer (admin split, option B): id 1 (owner, implicit admin) becomes tomigorn-admin, tomigorn gets a new requester user with his requests and his Holy Grail link.
-- Run on beefy with Seerr STOPPED, on db/db.sqlite3, after a .backup; parameters (docs/admin-split-plan.md, phase 2b, Seerr):
--   .parameter set :admin_email '<tomigorn-admin email>'
--   .parameter set :admin_sub '<tomigorn-admin Authentik uid>'
--   .parameter set :admin_jf_id '<Jellyfin user id of tomigorn-admin, no dashes>'
--   .parameter set :perms 8352
.bail on
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
CREATE TEMP TABLE guard (ok INTEGER CHECK (ok = 1));

-- A Seerr user tomigorn-admin may have created by pressing Holy Grail early: only if it owns nothing.
DELETE FROM "user" WHERE email = :admin_email AND id <> 1
  AND id NOT IN (SELECT requestedById FROM media_request WHERE requestedById IS NOT NULL)
  AND id NOT IN (SELECT requestedById FROM watchlist WHERE requestedById IS NOT NULL);

-- New everyday user: same Jellyfin identity, email and avatar as id 1 today, default permissions.
INSERT INTO "user" (email, username, permissions, avatar, userType, jellyfinUsername, jellyfinUserId, jellyfinDeviceId, avatarVersion, createdAt, updatedAt)
SELECT email || '.moving', username, :perms, avatar, userType, jellyfinUsername, jellyfinUserId, NULL, avatarVersion, createdAt, CURRENT_TIMESTAMP
FROM "user" WHERE id = 1 AND userType = 3 AND email NOT LIKE '%@%';
-- Aborts (nothing changed) unless id 1 is still the Jellyfin-type owner: a second run stops here.
INSERT INTO guard SELECT changes();
CREATE TEMP TABLE new_user AS SELECT max(id) AS id FROM "user";
INSERT INTO guard SELECT count(*) FROM "user" WHERE id = (SELECT id FROM new_user) AND email LIKE '%.moving';

UPDATE linked_accounts SET userId = (SELECT id FROM new_user) WHERE userId = 1 AND provider = 'holy-grail';
UPDATE media_request SET modifiedById = (SELECT id FROM new_user) WHERE requestedById = 1 AND modifiedById = 1;
UPDATE media_request SET requestedById = (SELECT id FROM new_user) WHERE requestedById = 1;
UPDATE watchlist SET requestedById = (SELECT id FROM new_user) WHERE requestedById = 1;
UPDATE issue SET createdById = (SELECT id FROM new_user) WHERE createdById = 1;
UPDATE issue_comment SET userId = (SELECT id FROM new_user) WHERE userId = 1;
UPDATE user_settings SET userId = (SELECT id FROM new_user) WHERE userId = 1;
UPDATE user_push_subscription SET userId = (SELECT id FROM new_user) WHERE userId = 1;

-- id 1 becomes tomigorn-admin; Seerr's Jellyfin scans run as id 1's Jellyfin user, so it must be a real one.
UPDATE "user" SET email = :admin_email, username = 'tomigorn-admin', jellyfinUsername = 'tomigorn-admin', jellyfinUserId = :admin_jf_id,
  jellyfinAuthToken = NULL, avatar = '/avatarproxy/' || :admin_jf_id, avatarVersion = NULL, avatarETag = NULL, updatedAt = CURRENT_TIMESTAMP
WHERE id = 1;
UPDATE "user" SET email = substr(email, 1, length(email) - length('.moving')) WHERE id = (SELECT id FROM new_user);
INSERT INTO linked_accounts (provider, sub, username, userId) VALUES ('holy-grail', :admin_sub, 'tomigorn-admin', 1);

-- Open sessions of id 1 belong to tomigorn's browsers: they must not turn into admin sessions.
DELETE FROM session WHERE json_extract(json, '$.userId') = 1;

SELECT 'user', id, username, jellyfinUsername, permissions, userType FROM "user" ORDER BY 2;
SELECT 'link', userId, provider, username FROM linked_accounts ORDER BY 2;
SELECT 'requests', requestedById, count(*) FROM media_request GROUP BY 2;
-- Any foreign-key violation aborts before COMMIT (guard CHECK fails, .bail stops, nothing is committed).
INSERT INTO guard SELECT (SELECT count(*) FROM pragma_foreign_key_check) = 0;
COMMIT;
PRAGMA integrity_check;
