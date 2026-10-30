import bpy, sys, math
from mathutils import Vector
bpy.ops.wm.open_mainfile(filepath=sys.argv[1])
sc=bpy.context.scene; sc.render.engine='CYCLES'; sc.cycles.samples=int(sys.argv[4]) if len(sys.argv)>4 else 24; sc.cycles.device='CPU'
sc.render.resolution_x=sc.render.resolution_y=900; sc.cycles.use_denoising=True
for o in sc.objects:
    if o.name.startswith('UCX'): o.hide_render=True
w=bpy.data.worlds.new('w'); sc.world=w; w.use_nodes=True; w.node_tree.nodes['Background'].inputs[0].default_value=(0.75,0.78,0.82,1); w.node_tree.nodes['Background'].inputs[1].default_value=0.8
sun=bpy.data.objects.new('sun',bpy.data.lights.new('sun','SUN')); sc.collection.objects.link(sun); sun.data.energy=3.5; sun.rotation_euler=(math.radians(40),0,math.radians(30)); sun.data.angle=math.radians(8)
cam=bpy.data.objects.new('cam',bpy.data.cameras.new('cam')); sc.collection.objects.link(cam); sc.camera=cam
v=[float(x) for x in sys.argv[3].split(',')]; az,el,dist,tz,lens=v[:5]; ty=v[5] if len(v)>5 else 0
cam.data.lens=lens
t=Vector((0,ty,tz)); d=Vector((math.sin(math.radians(az))*math.cos(math.radians(el)),-math.cos(math.radians(az))*math.cos(math.radians(el)),math.sin(math.radians(el))))
cam.location=t+d*dist; cam.rotation_euler=(-d).to_track_quat('-Z','Y').to_euler()
sc.render.filepath=sys.argv[2]; bpy.ops.render.render(write_still=True)
