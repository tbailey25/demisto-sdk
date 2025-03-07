import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import List, Optional

import demisto_sdk.commands.content_graph.neo4j_service as neo4j_service
from demisto_sdk.commands.common.constants import MarketplaceVersions
from demisto_sdk.commands.common.git_util import GitUtil
from demisto_sdk.commands.common.logger import logger
from demisto_sdk.commands.common.tools import download_content_graph
from demisto_sdk.commands.content_graph.common import (
    NEO4J_DATABASE_HTTP,
    NEO4J_PASSWORD,
    NEO4J_USERNAME,
)
from demisto_sdk.commands.content_graph.content_graph_builder import ContentGraphBuilder
from demisto_sdk.commands.content_graph.interface.graph import ContentGraphInterface


def create_content_graph(
    content_graph_interface: ContentGraphInterface,
    marketplace: MarketplaceVersions = MarketplaceVersions.XSOAR,
    dependencies: bool = True,
    output_path: Optional[Path] = None,
) -> None:
    """This function creates a new content graph database in neo4j from the content path

    Args:
        content_graph_interface (ContentGraphInterface): The content graph interface.
        marketplace (MarketplaceVersions): The marketplace to update.
        dependencies (bool): Whether to create the dependencies.
        output_path (Path): The path to export the graph zip to.
    """
    ContentGraphBuilder(content_graph_interface).create_graph()
    if dependencies:
        content_graph_interface.create_pack_dependencies()
    if output_path:
        output_path = output_path / marketplace.value
    content_graph_interface.export_graph(output_path)
    logger.info(
        f"Successfully created the content graph. UI representation is available at {NEO4J_DATABASE_HTTP} "
        f"(username: {NEO4J_USERNAME}, password: {NEO4J_PASSWORD})"
    )


def update_content_graph(
    content_graph_interface: ContentGraphInterface,
    marketplace: MarketplaceVersions = MarketplaceVersions.XSOAR,
    use_git: bool = False,
    imported_path: Optional[Path] = None,
    use_current: bool = False,
    packs_to_update: Optional[List[str]] = None,
    dependencies: bool = True,
    output_path: Optional[Path] = None,
) -> None:
    """This function updates a new content graph database in neo4j from the content path
    Args:
        content_graph_interface (ContentGraphInterface): The content graph interface.
        marketplace (MarketplaceVersions): The marketplace to update.
        use_git (bool): Whether to use git to get the packs to update.
        imported_path (Path): The path to the imported graph.
        use_current (bool): Whether to use the current graph.
        packs_to_update (List[str]): The packs to update.
        dependencies (bool): Whether to create the dependencies.
        output_path (Path): The path to export the graph zip to.
    """
    if packs_to_update is None:
        packs_to_update = []
    if os.getenv("DEMISTO_SDK_GRAPH_FORCE_CREATE"):
        logger.info("DEMISTO_SDK_GRAPH_FORCE_CREATE is set. Will create a new graph")
        create_content_graph(
            content_graph_interface, marketplace, dependencies, output_path
        )
        return

    builder = ContentGraphBuilder(content_graph_interface)
    if not use_current:
        content_graph_interface.clean_import_dir()
        if not imported_path:
            # getting the graph from remote, so we need to clean the import dir
            try:
                extract_remote_import_files(content_graph_interface)
            except RuntimeError as e:
                logger.warning(
                    "Failed to download the content graph, will create a new graph"
                )
                logger.debug(f"Runtime Error: {e}")
                create_content_graph(
                    content_graph_interface, marketplace, dependencies, output_path
                )
                return
    if not content_graph_interface.import_graph(imported_path):
        # if the import failed, we need to create a new graph
        create_content_graph(
            content_graph_interface, marketplace, dependencies, output_path
        )
        return

    if use_git and (commit := content_graph_interface.commit):
        packs_to_update.extend(GitUtil().get_all_changed_pack_ids(commit))

    packs_str = "\n".join([f"- {p}" for p in packs_to_update])
    logger.info(f"Updating the following packs:\n{packs_str}")
    builder.update_graph(packs_to_update)

    if dependencies:
        content_graph_interface.create_pack_dependencies()
    if output_path:
        output_path = output_path / marketplace.value
    content_graph_interface.export_graph(output_path)
    logger.info(
        f"Successfully updated the content graph. UI representation is available at {NEO4J_DATABASE_HTTP} "
        f"(username: {NEO4J_USERNAME}, password: {NEO4J_PASSWORD})"
    )


def extract_remote_import_files(content_graph_interface: ContentGraphInterface) -> None:
    """Get or create a content graph.
    If the graph is not in the bucket or there are network issues, it will create a new one.

    Args:
        content_graph_interface (ContentGraphInterface)
        builder (ContentGraphBuilder)

    """
    try:
        with NamedTemporaryFile() as temp_file:
            official_content_graph = download_content_graph(Path(temp_file.name))
            content_graph_interface.move_to_import_dir(official_content_graph)
    except Exception as e:
        raise RuntimeError("Failed to download the content graph") from e


def stop_content_graph() -> None:
    """
    This function stops the neo4j service if it is running.
    """
    neo4j_service.stop()
