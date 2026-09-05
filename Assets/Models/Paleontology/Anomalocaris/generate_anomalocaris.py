import bpy, math, os
from mathutils import Vector
from math import sin, cos, pi

OUT = os.path.abspath(os.path.dirname(__file__))
BLEND = os.path.join(OUT, 'Anomalocaris_canadensis_v01.blend')
FBX = os.path.join(OUT, 'Generated', 'Anomalocaris_canadensis_v01.fbx')
RENDER = os.path.join(OUT, 'Generated', 'anomalocaris_turntable.png')

# clean scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    pass

# collections
root = bpy.data.collections.new('ANOMALOCARIS_CANADENSIS')
bpy.context.scene.collection.children.link(root)
parts = {}
for name in ['Body', 'Swimming_Flaps', 'Head', 'Frontal_Appendages', 'Mouth', 'Tail_Fan', 'Eyes', 'Presentation']:
    c = bpy.data.collections.new(name)
    root.children.link(c)
    parts[name] = c

def move_to(obj, collection):
    for c in list(obj.users_collection): c.objects.unlink(obj)
    collection.objects.link(obj)

def mat(name, color, rough=0.5, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    bs = next((n for n in m.node_tree.nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'), None)
    bs.inputs['Base Color'].default_value = (*color, 1)
    bs.inputs['Roughness'].default_value = rough
    bs.inputs['Metallic'].default_value = metallic
    return m
body_mat = mat('Body_Teal', (0.025, 0.22, 0.23), 0.68)
flap_mat = mat('Flap_Amber', (0.42, 0.16, 0.025), 0.76)
append_mat = mat('Appendage_RedBrown', (0.24, 0.035, 0.018), 0.62)
mouth_mat = mat('Mouth_Dark', (0.028, 0.008, 0.004), 0.52)
tooth_mat = mat('Teeth_Ivory', (0.58, 0.30, 0.075), 0.5)
eye_mat = mat('Eye_Gloss', (0.006, 0.025, 0.032), 0.16, 0.05)
water_mat = mat('Display_Blue', (0.015, 0.05, 0.08), 0.3)

def finish_mesh(obj, bevel=0.0):
    """统一平滑法线，并给细长硬表面添加轻微倒角。"""
    for poly in obj.data.polygons:
        poly.use_smooth = True
    if bevel > 0.0:
        modifier = obj.modifiers.new('Edge_Soften', 'BEVEL')
        modifier.width = bevel
        modifier.segments = 2
        modifier.limit_method = 'ANGLE'

def uv(name, loc, scale, material, collection, seg=16, rings=8):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings, location=loc)
    o=bpy.context.object; o.name=name; o.scale=scale; bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(material); finish_mesh(o); move_to(o, collection); return o

def cyl_between(name, a, b, radius, material, collection, vertices=12):
    a,b=Vector(a),Vector(b); d=b-a
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=d.length, location=(a+b)/2)
    o=bpy.context.object; o.name=name; o.data.materials.append(material)
    o.rotation_mode='QUATERNION'; o.rotation_quaternion=d.to_track_quat('Z','Y'); finish_mesh(o, min(radius * 0.22, 0.0007)); move_to(o, collection); return o

def cone_between(name, a, b, r1, r2, material, collection):
    a,b=Vector(a),Vector(b); d=b-a
    bpy.ops.mesh.primitive_cone_add(vertices=10, radius1=r1, radius2=r2, depth=d.length, location=(a+b)/2)
    o=bpy.context.object; o.name=name; o.data.materials.append(material)
    o.rotation_mode='QUATERNION'; o.rotation_quaternion=d.to_track_quat('Z','Y'); finish_mesh(o, min(r1 * 0.2, 0.0005)); move_to(o, collection); return o

def fin(name, loc, scale, rot, material, collection):
    # flattened ellipsoid, used for swimming flaps and tail blades
    o=uv(name, loc, scale, material, collection, seg=16, rings=6)
    o.rotation_euler=rot
    return o

# Main dorsoventrally flattened body, 16 segment collars
uv('Body_Core', (0,0,0), (0.105,0.030,0.014), body_mat, parts['Body'], 24, 12)
for i in range(16):
    x=-0.072 + i*0.0096
    uv(f'Segment_{i+1:02d}', (x,0,0.002), (0.007,0.031,0.015), body_mat, parts['Body'], 16, 6)

# 16 paired swimming flaps, angled slightly backward
for i in range(16):
    x=-0.072 + i*0.0096
    z=0.001 + 0.002*sin(i/15*pi)
    span=0.030 - 0.006*abs(i-7.5)/7.5
    tilt=-0.12 + 0.05*sin(i/15*pi)
    for side in (-1,1):
        y=side*(0.030 + span*0.48)
        f=fin(f'Flap_{i+1:02d}_'+('L' if side<0 else 'R'), (x,y,z), (0.010,span,0.0032), (0,tilt*side,0), flap_mat, parts['Swimming_Flaps'])
        # subtle gill blade rows
        for g in range(3):
            gy=y + side*(0.008+g*0.005)
            uv(f'Gill_{i+1:02d}_{side}_{g}', (x-0.002,gy,z+0.003), (0.0025,0.004,0.0007), append_mat, parts['Swimming_Flaps'], 8, 4)

# Tail fan: three pairs plus central blade
for j, (xoff, span, zoff) in enumerate([(0.083,0.030,0.010),(0.070,0.034,0.008),(0.056,0.036,0.006)]):
    for side in (-1,1):
        fin(f'Tail_Blade_{j+1}_'+('L' if side<0 else 'R'), (-0.108-xoff*0.18, side*(0.018+span*0.35), zoff), (0.024,span,0.0038), (0, -0.35*side, 0), flap_mat, parts['Tail_Fan'])
fin('Tail_Central_Blade', (-0.132,0,0.010), (0.030,0.009,0.004), (0,0,0), flap_mat, parts['Tail_Fan'])

# Head plates and dorsal eyes
uv('Head_Plate', (0.094,0,0.001), (0.030,0.035,0.014), body_mat, parts['Head'], 20, 8)
for side in (-1,1):
    cyl_between('Eye_Stalk_'+str(side), (0.104,side*0.020,0.010), (0.113,side*0.033,0.028), 0.0032, append_mat, parts['Eyes'])
    uv('Eye_Ball_'+str(side), (0.114,side*0.034,0.029), (0.008,0.006,0.006), eye_mat, parts['Eyes'], 16, 8)
# three small rounded plates
for k in range(3):
    ang=2*pi*k/3
    uv(f'Head_Rounded_Plate_{k+1}', (0.094+0.012*cos(ang),0.022*sin(ang),-0.010), (0.010,0.008,0.003), flap_mat, parts['Head'], 12, 6)

# 14-segment frontal appendages, curved forward and outward
for side in (-1,1):
    pts=[]
    for j in range(15):
        t=j/14
        x=0.112 + 0.072*t
        y=side*(0.027 + 0.030*t + 0.008*sin(t*pi))
        z=0.003 + 0.010*sin(t*pi) - 0.004*t
        pts.append((x,y,z))
    for j in range(14):
        r=0.0052 - 0.0018*(j/13)
        cyl_between(f'Appendage_{side}_{j+1:02d}', pts[j], pts[j+1], r, append_mat, parts['Frontal_Appendages'])
        uv(f'Appendage_Joint_{side}_{j+1:02d}', pts[j], (r*1.18,r*1.18,r*0.85), append_mat, parts['Frontal_Appendages'], 12, 6)
        # alternating trident-like ventral spines
        if j % 2 == 0:
            p=Vector(pts[j+1]); base=(p.x,p.y,p.z-0.003)
            for q,dy in enumerate((-0.004,0,0.004)):
                tip=(p.x+0.004, p.y+side*dy, p.z-0.014-0.002*(q==1))
                cone_between(f'Spine_{side}_{j+1:02d}_{q}', base, tip, 0.0018, 0.0001, tooth_mat, parts['Frontal_Appendages'])

# Triradial oral cone, facing forward (torus axis X)
bpy.ops.mesh.primitive_torus_add(major_radius=0.020, minor_radius=0.0045, major_segments=24, minor_segments=8, location=(0.117,0,-0.012), rotation=(0,pi/2,0))
ring=bpy.context.object; ring.name='Triradial_Oral_Cone'; ring.data.materials.append(mouth_mat); move_to(ring, parts['Mouth'])
for k in range(12):
    a=2*pi*k/12
    y=0.020*cos(a); z=-0.012+0.020*sin(a)
    cone_between(f'Oral_Tooth_{k+1:02d}', (0.116,y,z), (0.107,y*1.18,-0.012+(z+0.012)*1.18), 0.0022, 0.0002, tooth_mat, parts['Mouth'])
for k in range(3):
    a=2*pi*k/3
    uv(f'Oral_Large_Plate_{k+1}', (0.116,0.014*cos(a),-0.012+0.014*sin(a)), (0.006,0.008,0.003), flap_mat, parts['Mouth'], 12, 6)

# presentation plane and camera
bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0,0,-0.040))
plane=bpy.context.object; plane.name='Presentation_Ground'; plane.data.materials.append(water_mat); move_to(plane, parts['Presentation'])
bpy.ops.object.camera_add(location=(0.48,-0.48,0.30))
cam=bpy.context.object; cam.name='Camera_Hero'; move_to(cam, parts['Presentation'])
def point_at(o, target): o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
point_at(cam,(0,0,0)); bpy.context.scene.camera=cam; cam.data.lens=58
bpy.ops.object.light_add(type='AREA', location=(0.18,-0.18,0.28)); key=bpy.context.object; key.name='Key_Light'; key.data.energy=8; key.data.shape='DISK'; key.data.size=0.25; point_at(key,(0,0,0)); move_to(key,parts['Presentation'])
bpy.ops.object.light_add(type='AREA', location=(-0.20,0.14,0.12)); fill=bpy.context.object; fill.name='Fill_Light'; fill.data.energy=2.5; fill.data.size=0.22; point_at(fill,(0,0,0)); move_to(fill,parts['Presentation'])

scene=bpy.context.scene
scene.render.engine='BLENDER_EEVEE'
scene.render.resolution_x=900; scene.render.resolution_y=600; scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'; scene.render.filepath=RENDER
scene.world.color=(0.002,0.004,0.008)
scene.view_settings.exposure=-0.1
scene.view_settings.view_transform='AgX'
try:
    scene.view_settings.look='AgX - Medium High Contrast'
except (TypeError, ValueError):
    pass
# metadata for downstream tooling
scene['species']='Anomalocaris canadensis'
scene['reference_length_m']=0.25
scene['length_parameter_range_m']='0.25-1.0'
scene['anatomical_basis']='ROM Burgess Shale page; Daley & Edgecombe 2014'
scene['model_status']='v02 medium detail / smoothed presentation mesh'

# 建立可在 Unity 中继续编辑的解剖层级。父级为空物体，不改变任何部件的世界坐标。
rig = bpy.data.objects.new('Anomalocaris_Rig', None)
root.objects.link(rig)
for collection_name in ['Body', 'Swimming_Flaps', 'Head', 'Frontal_Appendages', 'Mouth', 'Tail_Fan', 'Eyes']:
    group = bpy.data.objects.new(f'Anatomy_{collection_name}', None)
    root.objects.link(group)
    group.parent = rig
    for obj in list(parts[collection_name].objects):
        world_matrix = obj.matrix_world.copy()
        obj.parent = group
        obj.matrix_world = world_matrix

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
# select model collections only for export
bpy.ops.object.select_all(action='DESELECT')
rig.select_set(True)
for obj in [o for o in root.objects if o.name.startswith('Anatomy_')]:
    obj.select_set(True)
for c in [parts['Body'],parts['Swimming_Flaps'],parts['Head'],parts['Frontal_Appendages'],parts['Mouth'],parts['Tail_Fan'],parts['Eyes']]:
    for o in c.objects: o.select_set(True)
bpy.context.view_layer.objects.active=rig
os.makedirs(os.path.dirname(FBX), exist_ok=True)
bpy.ops.export_scene.fbx(filepath=FBX, use_selection=True, apply_scale_options='FBX_SCALE_ALL', object_types={'MESH', 'EMPTY'}, axis_forward='-Z', axis_up='Y')
bpy.context.scene.render.filepath=RENDER
bpy.ops.render.render(write_still=True)
print('WROTE', BLEND, FBX, RENDER)
