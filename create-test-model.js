// Quick test to see if the viewer works with a simple model
const THREE = require('three');
const { GLTFExporter } = require('three/examples/jsm/exporters/GLTFExporter.js');

const scene = new THREE.Scene();
const geometry = new THREE.BoxGeometry(1, 1, 1);
const material = new THREE.MeshStandardMaterial({ color: 0xffa500 });
const mesh = new THREE.Mesh(geometry, material);
scene.add(mesh);

const exporter = new GLTFExporter();
exporter.parse(scene, (gltf) => {
  console.log(gltf);
}, {});
