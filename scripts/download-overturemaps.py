from typing import Annotated
from pathlib import Path

import duckdb
from cyclopts import (
    App,
    Parameter,
)

download_app = App()


@download_app.default()
def download_overture_maps(
    release: Annotated[
        str,
        Parameter(
            help=(
                "Overture Maps Release. You can find a list of releases "
                "in the STAC catalog: https://stac.overturemaps.org/catalog.json"
            )
        ),
    ],
    xmin: float = -9.25,
    ymin: float = 38.56,
    xmax: float = -9.08,
    ymax: float = 38.70,
    output_path: Path = (
        Path(__file__) / "../../tests/data/almada_buildings.parquet"
    ).resolve(),
) -> None:
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial")
    conn.execute("SET s3_region = 'us-west-2'")

    conn.execute(f"""
        COPY (
            SELECT *
            FROM read_parquet(
                's3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*.parquet',
                hive_partitioning = false
            )
            WHERE bbox.xmin BETWEEN {xmin} AND {xmax}
              AND bbox.ymin BETWEEN {ymin} AND {ymax}
        )
        TO '{str(output_path)}' (FORMAT PARQUET)
    """)

    count = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{str(output_path)}')"
    ).fetchone()
    print(f"Wrote {count[0] if count else 'no'} features")

    print(
        conn.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{str(output_path)}') LIMIT 0"
        ).fetchall()
    )


# a provider config for this would be
# DuckdbFeatureProviderConfiguration(
#    source="read_parquet('tests/data/almada_buildings.parquet')",
#    geometry_column="geometry",
#    id_column="id",
#    storage_crs="http://www.opengis.net/def/crs/OGC/1.3/CRS84",
# )

if __name__ == "__main__":
    download_app()
