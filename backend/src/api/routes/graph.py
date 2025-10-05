"""Graph management API routes."""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, Dict, Any, List
import structlog

from ...services import Neo4jService, VectorService
from ...models.entities import Entity, EntityFilter, Person, Event, Location
from ...models.relationships import (
    Relationship,
    RelationshipFilter,
    GraphTraversalRequest,
    GraphVisualization
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/graph", tags=["graph"])


async def get_neo4j_service():
    async with Neo4jService() as service:
        yield service


async def get_vector_service():
    async with VectorService() as service:
        yield service


@router.post("/entities")
async def create_entity(
    entity: Entity,
    neo4j_service: Neo4jService = Depends(get_neo4j_service),
    vector_service: VectorService = Depends(get_vector_service)
):
    """
    Create a new entity in the graph.

    Args:
        entity: Entity to create

    Returns:
        Created entity with ID
    """
    try:
        entity_id = await neo4j_service.create_entity(entity)

        if entity.embedding:
            await vector_service.store_embedding(
                entity_id=entity_id,
                entity_type=entity.type.value,
                embedding=entity.embedding,
                metadata={"name": entity.name, "confidence": entity.confidence_score}
            )

        return {
            "status": "success",
            "entity_id": entity_id,
            "entity_type": entity.type.value
        }

    except Exception as e:
        logger.error("Entity creation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    include_relationships: bool = False,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Get entity details.

    Args:
        entity_id: Entity ID
        include_relationships: Whether to include relationships

    Returns:
        Entity data
    """
    try:
        entity = await neo4j_service.get_entity(entity_id)

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        response = {"entity": entity}

        if include_relationships:
            relationships = await neo4j_service.get_entity_relationships(entity_id)
            response["relationships"] = relationships

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get entity", error=str(e), entity_id=entity_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/entities/{entity_id}")
async def update_entity(
    entity_id: str,
    updates: Dict[str, Any],
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Update an entity.

    Args:
        entity_id: Entity ID
        updates: Properties to update

    Returns:
        Update confirmation
    """
    try:
        success = await neo4j_service.update_entity(entity_id, updates)

        if success:
            return {
                "status": "success",
                "message": f"Entity {entity_id} updated"
            }
        else:
            raise HTTPException(status_code=404, detail="Entity not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Entity update failed", error=str(e), entity_id=entity_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/entities/{entity_id}")
async def delete_entity(
    entity_id: str,
    neo4j_service: Neo4jService = Depends(get_neo4j_service),
    vector_service: VectorService = Depends(get_vector_service)
):
    """
    Delete an entity and its relationships.

    Args:
        entity_id: Entity ID

    Returns:
        Deletion confirmation
    """
    try:
        # Delete from Neo4j
        neo4j_success = await neo4j_service.delete_entity(entity_id)

        # Delete embedding
        vector_success = await vector_service.delete_embedding(entity_id)

        if neo4j_success:
            return {
                "status": "success",
                "message": f"Entity {entity_id} deleted",
                "embedding_deleted": vector_success
            }
        else:
            raise HTTPException(status_code=404, detail="Entity not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Entity deletion failed", error=str(e), entity_id=entity_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/relationships")
async def create_relationship(
    relationship: Relationship,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Create a relationship between entities.

    Args:
        relationship: Relationship to create

    Returns:
        Created relationship with ID
    """
    try:
        rel_id = await neo4j_service.create_relationship(relationship)

        return {
            "status": "success",
            "relationship_id": rel_id,
            "type": relationship.type.value
        }

    except Exception as e:
        logger.error("Relationship creation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/entities")
async def search_entities(
    filter: Optional[EntityFilter] = None,
    limit: int = 50,
    offset: int = 0,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Search for entities with filters.

    Args:
        filter: Entity filter criteria
        limit: Maximum results
        offset: Result offset

    Returns:
        List of matching entities
    """
    try:
        entities = await neo4j_service.find_entities(
            filter=filter,
            limit=limit,
            offset=offset
        )

        return {
            "count": len(entities),
            "limit": limit,
            "offset": offset,
            "entities": entities
        }

    except Exception as e:
        logger.error("Entity search failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/similar")
async def search_similar_entities(
    query_embedding: List[float],
    limit: int = 10,
    entity_types: Optional[List[str]] = None,
    threshold: float = 0.7,
    vector_service: VectorService = Depends(get_vector_service),
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Find similar entities based on embeddings.

    Args:
        query_embedding: Query embedding vector
        limit: Maximum results
        entity_types: Filter by entity types
        threshold: Similarity threshold

    Returns:
        List of similar entities
    """
    try:
        # Search for similar embeddings
        similar = await vector_service.similarity_search(
            query_embedding=query_embedding,
            limit=limit,
            entity_types=entity_types,
            threshold=threshold
        )

        # Enrich with entity data
        enriched = []
        for item in similar:
            entity = await neo4j_service.get_entity(item["entity_id"])
            if entity:
                enriched.append({
                    **item,
                    "entity": entity
                })

        return {
            "count": len(enriched),
            "threshold": threshold,
            "results": enriched
        }

    except Exception as e:
        logger.error("Similarity search failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/traverse")
async def traverse_graph(
    request: GraphTraversalRequest,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Traverse the graph from a starting entity.

    Args:
        request: Graph traversal parameters

    Returns:
        Traversal results with nodes and edges
    """
    try:
        result = await neo4j_service.traverse_graph(request)

        return {
            "status": "success",
            "start_entity": request.start_entity_id,
            "max_depth": request.max_depth,
            **result
        }

    except Exception as e:
        logger.error("Graph traversal failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entities/{entity_id}/relationships")
async def get_entity_relationships(
    entity_id: str,
    direction: str = "both",
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Get all relationships for an entity.

    Args:
        entity_id: Entity ID
        direction: Relationship direction (in, out, both)

    Returns:
        List of relationships
    """
    try:
        if direction not in ["in", "out", "both"]:
            raise HTTPException(
                status_code=400,
                detail="Direction must be 'in', 'out', or 'both'"
            )

        relationships = await neo4j_service.get_entity_relationships(
            entity_id,
            direction=direction
        )

        return {
            "entity_id": entity_id,
            "direction": direction,
            "count": len(relationships),
            "relationships": relationships
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get entity relationships",
            error=str(e),
            entity_id=entity_id
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visualize")
async def get_graph_visualization(
    config: GraphVisualization,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Get graph data for visualization.

    Args:
        config: Visualization configuration

    Returns:
        Graph data formatted for visualization
    """
    try:
        entities = await neo4j_service.find_entities(
            filter=config.entity_filter,
            limit=config.max_nodes
        )

        entity_ids = [e["id"] for e in entities]
        relationships = []

        for entity_id in entity_ids[:config.max_nodes]:
            rels = await neo4j_service.get_entity_relationships(entity_id)
            relationships.extend(rels[:config.max_edges // len(entity_ids)])

        nodes = [
            {
                "id": e["id"],
                "label": e.get("name", e["id"]),
                "type": e.get("type", "unknown"),
                "properties": e if config.show_properties else {}
            }
            for e in entities
        ]

        edges = [
            {
                "source": r.get("source", {}).get("id"),
                "target": r.get("target", {}).get("id"),
                "type": r.get("type"),
                "weight": r.get("weight", 1.0)
            }
            for r in relationships
            if r.get("source") and r.get("target")
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "layout": config.layout,
            "options": {
                "show_labels": config.show_labels,
                "show_properties": config.show_properties
            }
        }

    except Exception as e:
        logger.error("Graph visualization failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cypher")
async def execute_cypher_query(
    query: str,
    parameters: Optional[Dict[str, Any]] = None,
    neo4j_service: Neo4jService = Depends(get_neo4j_service)
):
    """
    Execute a raw Cypher query - returns mock data for demo.

    Args:
        query: Cypher query
        parameters: Query parameters

    Returns:
        Query results with sample memory data
    """
    try:
        # For demo mode, return mock data that matches the expected format
        from fastapi import Request
        
        # Get the app state to access mock data service
        # This is a workaround since we can't easily inject the mock service
        from ...main import app
        
        if hasattr(app.state, 'mock_data_service'):
            mock_service = app.state.mock_data_service
            
            # Convert mock data to the format expected by the frontend
            memories = mock_service.get_all_memories()
            relationships = mock_service.get_all_relationships()
            
            # Format as Neo4j results
            results = []
            for memory in memories:
                # Create a result that matches the frontend's expected format
                result = {
                    "n": {
                        "name": memory["name"],
                        "category": memory["category"],
                        "description": memory["description"],
                        "type": memory["type"]
                    },
                    "r": None,  # Will be filled by relationships
                    "m": None
                }
                results.append(result)
            
            # Add relationship data
            for rel in relationships:
                # Find source and target memories
                source_mem = next((m for m in memories if m["id"] == rel["source"]), None)
                target_mem = next((m for m in memories if m["id"] == rel["target"]), None)
                
                if source_mem and target_mem:
                    result = {
                        "n": {
                            "name": source_mem["name"],
                            "category": source_mem["category"],
                            "description": source_mem["description"],
                            "type": source_mem["type"]
                        },
                        "r": {
                            "type": rel["type"]
                        },
                        "m": {
                            "name": target_mem["name"],
                            "category": target_mem["category"],
                            "description": target_mem["description"],
                            "type": target_mem["type"]
                        }
                    }
                    results.append(result)
            
            return {
                "status": "success",
                "count": len(results),
                "results": results
            }
        else:
            # Fallback to empty results
            return {
                "status": "success",
                "count": 0,
                "results": []
            }

    except Exception as e:
        logger.error("Mock data query execution failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))