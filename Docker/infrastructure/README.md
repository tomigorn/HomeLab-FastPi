first run the compose project with

```bash
$ docker compose up -d
```

then connect to the postgresql with

```bash
$ docker exec -it postgresql bash
```

then inside the the container connect to the sql server with. make sure to use the username you defined in the .env file.

```bash
$ psql -h localhost -U postgres_user
```

you don't need your login because you're on the server itself. the login from the .env file would only be needed for remote connections.


then create the DB. you can check the DB with \l

```bash
$ CREATE DATABASE authentik;
CREATE DATABASE

$ \l                                                              List of databases
     Name      |     Owner     | Encoding | Locale Provider |  Collate   |   Ctype    | Locale | ICU Rules |        Access privileges        
---------------+---------------+----------+-----------------+------------+------------+--------+-----------+---------------------------------
 authentik     | postgres_user | UTF8     | libc            | en_US.utf8 | en_US.utf8 |        |           | 
 postgres      | postgres_user | UTF8     | libc            | en_US.utf8 | en_US.utf8 |        |           | 
 postgres_user | postgres_user | UTF8     | libc            | en_US.utf8 | en_US.utf8 |        |           | 
 template0     | postgres_user | UTF8     | libc            | en_US.utf8 | en_US.utf8 |        |           | =c/postgres_user               +
               |               |          |                 |            |            |        |           | postgres_user=CTc/postgres_user
 template1     | postgres_user | UTF8     | libc            | en_US.utf8 | en_US.utf8 |        |           | =c/postgres_user               +
               |               |          |                 |            |            |        |           | postgres_user=CTc/postgres_user
(5 rows)
```

then create the authentik_db_user (or different name, same as in .env). make sure to use the password you generated in the .env file.
and give it all priviledges. check the created user with \du.

```bash
$ CREATE USER authentik_db_user WITH PASSWORD 'authentik_postgresql_password';
CREATE ROLE

$ GRANT ALL PRIVILEGES ON DATABASE authentik TO authentik_db_user;
GRANT

$ \du
                                 List of roles
     Role name     |                         Attributes                         
-------------------+------------------------------------------------------------
 authentik_db_user | 
 postgres_user     | Superuser, Create role, Create DB, Replication, Bypass RLS
```

Next, change ownership and grant schema permissions of authentik database to authentik_db_user:

```bash
$ ALTER DATABASE authentik OWNER TO authentik_db_user;
ALTER DATABASE

$ GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO authentik_db_user;
GRANT

$ GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO authentik_db_user;
GRANT

$ GRANT CREATE ON SCHEMA public TO authentik_db_user;
GRANT
```

you can exit the postgresql with \q and then exit the docker container with exit
```bash
$ \q

$ exit
exit
```