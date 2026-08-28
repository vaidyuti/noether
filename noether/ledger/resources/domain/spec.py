"""Domain serialization. Domains are registry configs (DomainRegistry), not
user-authored payloads, so the spec is a serializer function rather than a
NoetherResource."""


def serialize_domain(config, detail=False):
    data = {"slug": config.slug, "name": config.name, "version": config.version}
    if detail:
        data["account_types"] = [
            {"name": t.name, "normal_balance": t.normal_balance} for t in config.account_types
        ]
        data["default_units"] = [
            {"symbol": u.symbol, "name": u.name, "precision": u.precision}
            for u in config.default_units
        ]
        data["chart_templates"] = [
            {
                "name": template.name,
                "nodes": [
                    {
                        "path": node.path,
                        "account_type": node.account_type,
                        "unit": node.unit,
                        "placeholder": node.placeholder,
                    }
                    for node in template.nodes
                ],
            }
            for template in config.chart_templates
        ]
    return data
