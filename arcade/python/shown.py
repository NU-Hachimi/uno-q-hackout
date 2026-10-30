"""What an owner shows that comes and goes step by step (bullets, the hook head, dust rings, the finisher's flash):
its objects() as nodes in alia-engine's world, pooled by mesh. The Player, the Boss and the Finisher each hold one
and call sync() once a step, so the world shows what they are, with nothing in between. Objects have no identity
from one step to the next, so they are placed without blending (teleport)."""

import assets
from gen import palette


class Shown:
    def __init__(self, w):
        self.w = w
        self.pool = {}  # mesh id -> nodes

    def sync(self, objects):
        used = {}
        for o in objects:
            handle = assets.MESHES.get(o.mesh)
            if not handle:
                continue
            nodes = self.pool.setdefault(o.mesh, [])
            n = used.get(o.mesh, 0)
            if n == len(nodes):
                nodes.append(self.w.spawn(handle))
            node = nodes[n]
            used[o.mesh] = n + 1
            node.position, node.scale = (o.x, o.y, o.z), o.scale
            node.set_rotation(o.yaw, o.pitch, 0.0)
            node.tint, node.ground_fog, node.active = o.tint, o.tint != palette.FLASH, True
            node.teleport()
        for mesh_id, nodes in self.pool.items():
            for node in nodes[used.get(mesh_id, 0):]:
                node.active = False

    def close(self):
        for nodes in self.pool.values():
            for node in nodes:
                if node.alive:
                    node.destroy()
        self.pool = {}
