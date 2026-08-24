# potto CLI

The potto CLI allows an admin user to perform all sort of operations.


## Examples

### Manage collections

The CLI has commands for managing collections


#### List collections

```shell
potto collection list
```


#### Get details of a collection

```shell
potto collection detail <collection-identifier>
```


#### Create collections

Creating a collection requires that you explicitly use the `--collection` style when passing in the collection
representation.

```shell
docker compose --env-file docker/local.env -f docker/compose.dev.yaml exec potto \
  uv run potto collection create-feature --collection \
  '{"resource_identifier": "test-db-collections", "english_title": "collections from the db", "is_public": true, "spatial_extent": "POLYGON ((-14.0625 35.317366, -3.955078 35.317366, -3.955078 44.715514, -14.0625 44.715514, -14.0625 35.317366))", "provider": {"provider-name": "postgis", "config": {"db_dsn": "postgresql+psycopg://potto:pottopass@db:5432/potto", "db_object": "collection", "geometry_column": "spatial_extent", "id_column": "id"}}}'

```



#### Delete collection

```shell
potto collection delete <collection-identifier>
```
