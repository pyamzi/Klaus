# Upstream: Image Occlusion Enhanced

- Source: `~/Library/Application Support/Anki2/addons21/1374772155/` (AnkiWeb 1374772155)
- Version: v1.4.0
- Project: https://github.com/glutanimate/image-occlusion-enhanced
- Licence: AGPL-3 with Section 7 additions, see `LICENSE.txt`. Every copyright header is kept.

Copied verbatim. Not copied: IOE's own `__init__.py` (the add-on bootstrap; ours is Klaus's `setup()`/`occlude()`),
`manifest.json`, `meta.json`, `CHANGELOG.md`, `__pycache__`.

Later tasks edit some `.py` files here. The sha256 below is of the file as vendored, so the
diff against upstream stays recoverable after those edits. Data files (everything that is
not `.py`) must still match.

Modified by Task 2 (Klaus rules: window-modal asks, gui_hooks, no `parent` shadow, `col.get_config`/`set_config`, web path): `add.py`, `config.py`, `consts.py`, `dialogs.py`, `editor.py`, `main.py`, `nconvert.py`, `ngen.py`, `options.py`, `web.py`.

Also modified by Task 3 (wiring): `add.py` (`occlude(image_path, initial_svg)` returns True; add mode loads `initial_svg` through svg-edit's `url` item), `main.py` (no `setConfigAction`; menu labels "Image Occlusion Options…" and "Image Occlusion Help…"; origin from `editor.addMode`; `on_profile_loaded` logs instead of raising), `add.py` again (`_current_deck_id`: Anki 26.09's NewAddCards has no deck chooser).

Also modified by Task 7 ("Draw a diagram…"): `add.py` (`occlude(..., draw)` opens on a blank PNG with the Draw tab; `use_drawing`; Add waits for a drawing; the `_<image>.excalidraw` sidecar after the notes are added; Change Image clears it), `editor.py` (`add_draw_tab`, `set_add_enabled`, the Draw tab shut down on close; fix round: `reject()` is the one discard gate, also for an unused or changed drawing, and the title-bar X and the Close button go through it; the editor closes with its Add/Edit window), `main.py` (the Add editor's I/O button offers "Choose image…" and "Draw a diagram…"), `ngen.py` (`generateNotes` keeps the media name Anki returned as `media_name`).

Also modified by Task 8 (re-edit a diagram): `add.py` (edit mode adds the Draw tab, loaded with the saved scene, when the note's image has a readable `_<image>.excalidraw`; "Use drawing" on top of an earlier drawing reads svg-edit's masks back and carries them over with `remap_masks`; an update writes the new scene beside the new image name), `editor.py` (`add_draw_tab(on_use, start)`: without `start` the Masks Editor stays current and Add is not blocked), `ngen.py` (`_finishUpdate` keeps the returned media name as `media_name` too).

Klaus additions, not part of IOE and not hashed below: `__init__.py`, `excalidraw/` (the offline Excalidraw page, Task 5; `scripts/build_excalidraw.sh` produces it, so edit the script, not the bundle; font licences in `excalidraw/fonts/LICENSES.txt`), `excal_masks.py` (label masks from an Excalidraw scene, Task 6), `excal_tab.py` (the occlusion editor's Draw tab, Task 7) and `svg-edit/LICENSE-svg-edit.txt`.

`svg-edit/LICENSE-svg-edit.txt` is svg-edit's MIT licence, which IOE's copy of svg-edit 2.6 did not carry (its file headers say MIT). It is svg-edit's `LICENSE` verbatim from https://github.com/SVG-Edit/svgedit at commit `92b9f6abeaca87aafa71aeba73658e7962896df9` (branch `svn/2.6`, the line IOE vendors), sha256 `8d2e7662c8903c04205ed16f610285998a92a7b22384426c0b19a68793447e2a`.

```
3b530b4274f7458b02fa4cfdb8f876aa1befb208641ffa47d1f493dfa02e05e6  LICENSE.txt
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855  _vendor/imagesize/__init__.py
ebd2b795072137439595aaf614a6a3f278f8c00082a1b16fd8ef3daa5233a326  _vendor/imagesize/imagesize.py
2f08102d7d2e0d658bcf9a908913886617db93e9a0282762b2fd688e4fdb4f1d  _vendor/imghdr.py
99fc90387792e3209e946dd9a3e077ee32c760db88e649caff6b6e991faa85ed  _version.py
72bd5c4d5822d9c2789e726e2d67d69ce27dc18e73b2de0f80aa3cc0e3ac66f7  add.py
1175980b83f2b585ce3b4dd5b43703c2f42b0894b6589b421c72e5893ffac735  config.py
86278d7d68e2bf61f7cdfab3184e723e1a084e12513b2c6c239d076ba8120a0a  consts.py
697a47896b011526fa3225bae9985a4afc6ce91e96c84a06f0be27eb18a9f63e  dialogs.py
5c208712290edfd15206bc07d53e29280fe57c18bcb3b9ae6f89bd48ec197c38  editor.py
3f38e8f193f36b5442918877455dc61e077b12175a03e06e96e5489b4ba93c04  icons/add.png
038cbbfb427345ef2d9d016f5f5494f357b4417317ccbd53b44bc8a0c2d1ce61  icons/edit.png
483c4a0396691993a641ec409c44b8b7e1daab0ae7e2b2944c4bc59520bb7655  icons/loader.gif
29d617937e50e431617f5d969093788be4868fd406138d58f7b2601aaddccac9  lang.py
93b08265ddc4041df88eafa90f118d9e96302087779a2e89f4bd03f8df78be92  main.py
06e69b69b3e58aaf3974d613b70b2450ef6cd9f3d9c0978a1b5f76c714514b00  nconvert.py
bb611389ce60e3f46adcd738f9e723a677a77d05028d1c0bea7a50e12f89d7be  ngen.py
e2a39aadb8edcb480924898915b2fa01d411c09919a4f4a875cb9ae746c135ad  options.py
c5e21f42bc3c1488b2af5b2b50aa6cfe3a3f6270d1879eec2ac2105ab1724af2  qt.py
0893af082c7889008e1fc996b5e2f2a17740ca484eb1ca627437909e8c94df8e  svg-edit/editor/browser-not-supported.html
b3ae36a619eb491ca911d3ee2f42cf13af3ddf696a7c976352827d7ca8a8b997  svg-edit/editor/browser.js
4e89ca096e2e95b90ea62953110e8ae26fe6c44300e2f73a96eafa6104a1b1e9  svg-edit/editor/canvg/canvg.js
5d8d2e2a2a7d535f1f39a40ce0fb7b4a26006590a32e3584abe3894bfd583936  svg-edit/editor/canvg/rgbcolor.js
0f3860dc45672dbd8fb3b0b7cb200fff0eb409f2037e810347ece47d22a476d2  svg-edit/editor/contextmenu.js
69096f816ea30abcdf60c6b67e3a13a1392359318e94a94110e1c9ede08d0a5c  svg-edit/editor/contextmenu/jquery.contextMenu.js
7f4220d2630cc837d58f8fc3c96eee56be447906270abb538f7505db6341049d  svg-edit/editor/draw.js
73adb8f713e6af6f723c58d8f9a9aaa22379e0fdcf26ec8f105879105a2ce18d  svg-edit/editor/embedapi.html
7dbad973f724bccb14f942e0ed8b18aeae3e9080d00362664c31ffce460773d9  svg-edit/editor/embedapi.js
61b950788f70ab7b05e0ea711a7851c458f019a63e469af20a317680d7c2102d  svg-edit/editor/extensions/closepath_icons.svg
e9d2e4b5de435a92718a6d91f8a876f6069b444c7c50c33a79a32c24932b0849  svg-edit/editor/extensions/ext-arrows.js
32654eda799fd06621f7b82692207a5b214416d1226e738d5f20d4c9181d6900  svg-edit/editor/extensions/ext-closepath.js
0e7fa9b6adf0958ea1da630fa73dc0db1bf7985a12e3c2d8b34f87ba2009abd1  svg-edit/editor/extensions/ext-connector.js
c5fdaf02455a933b8dcedcf38d13beb5e160fd11bd613a74dd4b54d5ef0aaf4b  svg-edit/editor/extensions/ext-eyedropper.js
1a1e6d2a247bbf6acd37e237ee240698e18c9c7e50dc254b07830fc1e4bab7de  svg-edit/editor/extensions/ext-foreignobject.js
35a895720512bfd3038a5dffdf1d8742f2c09c92388d0292dbccae9a5df70208  svg-edit/editor/extensions/ext-grid.js
afc92b95d5eaf621c6338d4255559386b465d15d4728bb0a0e1a1f33d85c198e  svg-edit/editor/extensions/ext-helloworld.js
e6d2944642ddb6a63372c3938a2945b2c94274d515efbe36dc83a8a113b7b306  svg-edit/editor/extensions/ext-image-occlusion.js
34ca18a6b4144d46f533789745ef50c9ba0a309d7270323f3ae2fa3fee25e455  svg-edit/editor/extensions/ext-imagelib.js
58b005fdafd934b724345aa3608081a912b763dac46ed88c4d24926bb0c820e9  svg-edit/editor/extensions/ext-imagelib.xml
ef608ecfe3705d053bf5a73a0a7b5d745bac042fab6d20af50af710052a242fa  svg-edit/editor/extensions/ext-markers.js
58e6b87f9308a639ca65d8b9911b68b267485655ea492c16801a70ceead9a74e  svg-edit/editor/extensions/ext-panning.js
b6376338213d4351cb482466de8e0b355dfb2a373c1708cba3d1004dc9fd7327  svg-edit/editor/extensions/ext-panning.xml
c21366af52282de9ce558b66abb11bc7c3f0b50b1e947fc706d08011515a591f  svg-edit/editor/extensions/ext-server_moinsave.js
e31df3f6f52cabb8ddfc5a64cc132a562c4172808fa9ab908948a0656d20f65b  svg-edit/editor/extensions/ext-server_opensave.js
e2623bf949e69abfb792947bd647f0b7df6d0d17bcc3d49fa53658ceaa2f1680  svg-edit/editor/extensions/ext-shapes.js
b30e50a3b217283166a2e20aa90c8d76b263f6ec6c5c47593eeb38036b66f019  svg-edit/editor/extensions/ext-shapes.xml
a1c21cf0c09b13471f1acb691768dbdc4b49ed7d903b3f76db03b6d158de6529  svg-edit/editor/extensions/ext-snapping.js
d737b41472f8a84f0062b9ae4062afc5e40d4a51b75f8d61f8bcda28c7cbcf75  svg-edit/editor/extensions/eyedropper-icon.xml
182f2348459782c91e7a194ca3af8852d954d29d1804ebed851b8ac777ba144f  svg-edit/editor/extensions/eyedropper.png
3eaa71bda415dd7af0b82deb304fd6d80d046b04824a8908ab821c603c43dfc7  svg-edit/editor/extensions/fileopen.php
245cdef7df946d7c3de5ca1abd607910410d4300b2cb54cf95b1524c99ef8b24  svg-edit/editor/extensions/filesave.php
0e36fccd478038f61c3070143d0035e51e34d9fb6eae21de2f2e7ae5b34d2f56  svg-edit/editor/extensions/foreignobject-icons.xml
7eac845b9f51a955b39a689c7b352aae22e418ede3b93e5e953bac1ba80c10f2  svg-edit/editor/extensions/grid-icon.xml
6a73cf9c6ddc51c811e789172bbdbe333b2fec99c5943be703129c50adcf90f3  svg-edit/editor/extensions/helloworld-icon.xml
5f911c3224d6b2155ae31419b7484faea4daed14a1d277cbc72d21d9a60416dd  svg-edit/editor/extensions/image-occlusion-icon.xml
33cc1a2f945c08b16e92a66fcaab4bcd2d54f02d9f3f1f737d79df68e951ae2a  svg-edit/editor/extensions/imagelib/index.html
bb317c93f5beb39b48e2d4dffc8a5fda3c19a0239336f2a3a9fb729b84ecfcd6  svg-edit/editor/extensions/imagelib/smiley.svg
aa0e71735a3183c8666a0c8a9fe195137aa6ed2a56acad20c9928037a6306a37  svg-edit/editor/extensions/markers-icons.xml
afe463d00d8b79cbfa0eb89a56ac7bc865045523470777c2e031b55d0ddb1954  svg-edit/editor/extensions/shapelib/animal.json
66894c33f105824ab4525015955c2545909756a2476802620817945011098f61  svg-edit/editor/extensions/shapelib/arrow.json
6f966eaf25f3502f69829ee1ce6ea8868875b070792a8e5e873340fe58b18971  svg-edit/editor/extensions/shapelib/dialog_balloon.json
ca441d2d2532d28efe9a4f8a08e2551192333b7c96a9f1b8cf4359d7ac6e6452  svg-edit/editor/extensions/shapelib/electronics.json
9d2e016ca71aada0edd58828a8c64d1553ab77012bbefdd15e5c688d4b599882  svg-edit/editor/extensions/shapelib/flowchart.json
e7a0f170aa78bd8e5a2b79edbb9d41944018d3aa89f650852f928687504a6ed5  svg-edit/editor/extensions/shapelib/game.json
32423b3fa815e5dec59e2275b96b8f07c774a84cdb69ede4ad6525a0d4da16b7  svg-edit/editor/extensions/shapelib/math.json
3f62ac8b72286e799a61605ee20355fd92df692320c74ec165238ab2071efea8  svg-edit/editor/extensions/shapelib/misc.json
19698893e5cc3e38abdcc35a8b1f225e34b95cf2b71b5ddf23eebebd44baeef9  svg-edit/editor/extensions/shapelib/music.json
e6926e746b96d30d41d694a5b356e2b39d298b74faf9de6a2f081aac79a65408  svg-edit/editor/extensions/shapelib/object.json
ac7098161f1aa780779129b97df3bfa29747be3779dbc04a8c913439d45fc794  svg-edit/editor/extensions/shapelib/raphael.txt
34218733aa58592d77a1c1e002cc6fe34ec7e737661064c9f671b845bb906304  svg-edit/editor/extensions/shapelib/raphael_1.json
9d9d0422ab6420bb3705798461b43ed66c508d5d0a30213295a97f145eccd071  svg-edit/editor/extensions/shapelib/raphael_2.json
5d28b9dfbf0aaa7aef22e45d168906de4f3ebd93eed6200c8745a6dfd0397e8f  svg-edit/editor/extensions/shapelib/symbol.json
2cdfe62571038e3486a92d7d8ae74349f7e1f8df8a16cd0f125ae786743a5e12  svg-edit/editor/extensions/snap-icon.xml
d7f2c9c3283537e86ed586bf14a81f68ecca07f211017583ee8d183c9f6e3ee2  svg-edit/editor/history.js
aec33987f60cbf907eda2a93171f3c8bbeacbd7c7b2582007ae9d7b194e288f9  svg-edit/editor/images/README.txt
62c02e3aa2adc79b61565dbe36aeb2a769ab755860df4eea164846dce3bf637a  svg-edit/editor/images/align-bottom.png
3ce33c24a740b2b06c663c59920ed0928da2d8f7916d5611268d4697cec8a026  svg-edit/editor/images/align-bottom.svg
4812e3f6ac14e8c9afa6315ff6210e4d22ad7b18e4671ceaf96cbf7d4044c31d  svg-edit/editor/images/align-center.png
25128839fa84db4803fdad5cec99e1a92605e6365ef92ee518d0e4d2fa2a7f62  svg-edit/editor/images/align-center.svg
5b63e4b6504f31cfeee4ae15be397314934f2589c4b2129bdb755e124b358d3c  svg-edit/editor/images/align-left.png
850c8fd5ee1805c4ee1b0369be0bc1a546d7e5c3ccb5bec5ca8f8db55779ccf5  svg-edit/editor/images/align-left.svg
1166dbdc483c9fd0267f3cf951cfaeceb0b426640fc0c2f022ae00a657b1fa7a  svg-edit/editor/images/align-middle.png
735adb2951e8c11cef0593b7004dc9ed703d2e54d0192c4d229957d206df895a  svg-edit/editor/images/align-middle.svg
0a87d77a98d3df13b8bf7f82af651c110657cb9708bc40cdcc90ba2489f0492e  svg-edit/editor/images/align-right.png
9c8420eacb2f3fc9f5259a6f8b19fd89cbc9969f255c5d32b7048fa6b7d6b38a  svg-edit/editor/images/align-right.svg
bf7f1aac631fcb78bb7e4e776a551f18ca2a8cf38f0129e3a0872a40db7d70c3  svg-edit/editor/images/align-top.png
cc4f6417f5823954632257fad27a4de295c72222df121e818ea2905feb71b45c  svg-edit/editor/images/align-top.svg
c64149a5242474a53b1cd2d6e8c170f76af01ae8739ac0de14934e22045c6be4  svg-edit/editor/images/bold.png
24647bb3c3f4eb1b0770e9a5157caf504e996569cd0bae191be42bb16eb05ea8  svg-edit/editor/images/cancel.png
aac32a9a486692f465be55473e6c1e91208459691faefd173d419639e065d25b  svg-edit/editor/images/circle.png
241b54ff8660a3b8f3dafc6096274218a5dd8f4e8121334255e1b82636c22231  svg-edit/editor/images/clear.png
c216a80fd6430b7220b7f311390e72c7e7e9624719d339475a5569ee0402fe3d  svg-edit/editor/images/clone.png
decf212d57083d3173c901ae819dcb96fdc736e23b64bdf3dbb1be0cd98afc8a  svg-edit/editor/images/conn.svg
05ca4c4713ddb82fd08670f42cf7852849c934f3787650eec3b47245232473c9  svg-edit/editor/images/copy.png
53efaddd11d07f35886dcecc31747f4f10eac192f2f020d13aefa164b802412b  svg-edit/editor/images/cut.png
dd5e1672e24cbb83c807bdf72d8513c81c236e1e43114b655fa052665590db2d  svg-edit/editor/images/delete.png
1f08d1e567c452765e980f0e72fdb22d4b588b124079a8b69d92339406851c42  svg-edit/editor/images/document-properties.png
f2f6c8ee3985d3225ce8a345b499dc7c4e765ad2e7530ae14fa156c1526839ee  svg-edit/editor/images/dropdown.gif
6f99e47dacfeae41427235239e316637159e940cad03395d4290c4ebd5604e17  svg-edit/editor/images/ellipse.png
f47f678ea59f71416bc8ae35601a83d18a7396a6f16d2bf429a8897b3d0a57fc  svg-edit/editor/images/eye.png
fb332ccde901252eaa0d6104df4908e6fd4420b376da7f00f9b9748cb963f102  svg-edit/editor/images/fhpath.png
432c27702310f543c2ad618bc77ada919a85669b81c49803a90ec731fc36ed44  svg-edit/editor/images/flyouth.png
37ccf5660c69c9e028572fc1c73e43c04ff8f828c8ee7255fc9612bb2978cd81  svg-edit/editor/images/flyup.gif
d0e18e8c5912b8bcbecf57283b3741413fbc31cc67dc69903738db4404bc704f  svg-edit/editor/images/freehand-circle.png
72cea2bcbbe7af955e536cf0cbe23ae2ff75891e10809ff1b0de238b6d684e11  svg-edit/editor/images/freehand-square.png
cc329e12fa329888328748bc65d4d4f455265563d749fbff7b0deeebf6f3ba68  svg-edit/editor/images/go-down.png
6d4ae7517a2914b5de787ebe33efc2915d5872f4d0c5839a0f84149adedb306e  svg-edit/editor/images/go-up.png
7bc1d06a5e88a983ffebf9b703d9d44de7c494c4239ef24517c4d088134b6276  svg-edit/editor/images/image.png
adcda0565bc1388b09f359864350cc39ac3fae32b8920ca1689eb0ac73068913  svg-edit/editor/images/italic.png
e0fec8634c5fa6288c3e883fba74f3ea73abc1d11c8c2184561ee8395cf3af21  svg-edit/editor/images/line.png
5438b8c5b93a5637b7fd7345b2d74f679a221d696af1375077cc7fe7ff6cbb21  svg-edit/editor/images/link_controls.png
dd9c05fd50221bfebc094cc7e5f2d9fa9fafabf17ca0abca9743f3e27da8096b  svg-edit/editor/images/logo.png
c3af3a16b66dfafea55e8509f2a2140f90fb0fb3a2af7f865345867d54791ace  svg-edit/editor/images/logo.svg
2c1f04fb34596ab459d6879a7b1ab0d34ba5489f2a19f81183a23998517d1207  svg-edit/editor/images/move_bottom.png
95f561ef9518af785b0ea1675231a7a6debeff07b9ce16ddf5747450a8b56b4b  svg-edit/editor/images/move_top.png
2c8306387acc92d856e41b06e525f3c7ed35615319ff7eb1823323ce882f145e  svg-edit/editor/images/node_clone.png
1bd17ecf59abc25531ddb1ad377c1ffc486c0120696e7cdb0efbba1b52b36034  svg-edit/editor/images/node_delete.png
0998197451fbd7e206c8d3454d9792865d24add02e827bb18d20549dd65a24d7  svg-edit/editor/images/none.png
e4dec59a0d31a66e566f51adc462fd1a4e4932534864669e576ff84bb5d9533a  svg-edit/editor/images/open.png
288e7cba52cbfe648b343ea22091a62d08cf410e8435139eb4e10b8cb6901707  svg-edit/editor/images/paste.png
a377f1fe7ae275ac2f6cc6cdbdb32c44f5067ef118be1a89651720b76c6094a4  svg-edit/editor/images/path.png
4dc629f9e155ffbe84784bf2d552a94130bc99587f55ff477099739c04a1f24a  svg-edit/editor/images/polygon.png
068ec878331aaf2515dc02b45878b32e4faf34ca2ef59c208a118618fc679caa  svg-edit/editor/images/polygon.svg
6075070731a999344f8300e427a1a89d3a15863cc12925254f1fef309b9415eb  svg-edit/editor/images/rect.png
16207e8b12153a8fbb13a90f4018f6468a4d25111802dd208f7d29a384bb9b69  svg-edit/editor/images/redo.png
a4d6da534eba611d679f5629418d49163749d55dc07e6719de410feb8e490464  svg-edit/editor/images/reorient.png
a731c93430e557ba23a17a5eb99c90b32d052a60a45ba723db086da458450d16  svg-edit/editor/images/rotate.png
3d3515e582b63b3300dfcde28d8f5614f7418225c4c2f3b71535806038f61100  svg-edit/editor/images/save.png
64d35db59d5a7440d8f7b702a88964f2e624a54b1d81721e80772e4a6e8de247  svg-edit/editor/images/select.png
30bc3aad0f9423af1ca097ea87c6758dd85d759bb7efc900bc621315a9bdb15c  svg-edit/editor/images/select_node.png
0d561fdeaa0cecf5996f90287db9b052b08326ca92720cf9a9531fb4f3863225  svg-edit/editor/images/sep.png
bec165c7a7802ffa2990cbafde98b768a4cb2bb11a80427755a768a02bd3c4bd  svg-edit/editor/images/shape_group.png
9b068137ae83ba6f53703fde7c8e5608b5e2eebf8297cff729a7836c3d59e76c  svg-edit/editor/images/shape_ungroup.png
fc9e2ccc8e56aa095e820c0bc85bc5dba6fa955f780b991602163a0b35c3f4fc  svg-edit/editor/images/source.png
63db3fcb0d35e18fafb5edceeb853f547d21fb5b4c83fe0198874b6e992a8115  svg-edit/editor/images/spinbtn_updn_big.png
ae7fc3c4999144b234414e10e512107c680e44201dbec5e892ddf90f61c0d9ed  svg-edit/editor/images/square.png
1757371ae7d9b8531076993982d71c26bb6bf98142d93ca1d0ca526e5a6bdf62  svg-edit/editor/images/svg_edit_icons.svg
e25b49ea691d10e6a4c70e88151d25ead615707a13603d622c423ccb80e393e1  svg-edit/editor/images/svg_edit_icons.svgz
dcf05065fc152e85949400d45fe1589cd72d4f7810275a8843d7dc5762360fdc  svg-edit/editor/images/text.png
c609a3e62115fbeaca77346bc66de1291aacf6809eaa510e96e5dea772182b95  svg-edit/editor/images/text.svg
2121ccca8cef01b0bd7c5bbfcb90eafad44cb69f289915711d9638ab4d6f6d93  svg-edit/editor/images/to_path.png
405aebbe7114b62bfe67067d92960e5cf274e0424b0e88097d4baa35bfbfc0f8  svg-edit/editor/images/undo.png
703a4a6ce68fd291029381e0aa31cd47e94c2b16924b3c84c64e9482cec90764  svg-edit/editor/images/view-refresh.png
5991924674020200615cc77163ade8e57164a3a1a1a88342d83557d8eea4e91b  svg-edit/editor/images/wave.png
fa205c2ee1ef17b68281e2be816cec61ece023dac6d46ee24a1a6971ae6c3f18  svg-edit/editor/images/wireframe.png
e5c4c2bbfedf37422b52a3854189384dff096d3bdbd50262083c0b59a93352da  svg-edit/editor/images/zoom.png
cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30  svg-edit/editor/jgraduate/LICENSE
09a263f2a4c7cafca42328c0bac94965974571edcb22a69c251ba936948cae3b  svg-edit/editor/jgraduate/README
21da7dc5e59254d17d4f3f83c1e79f251cc35fc17a291df1b69b7604ec215571  svg-edit/editor/jgraduate/css/jPicker.css
ef3541d3964c727ee6cc90c0fa286c1ec7eefe22d219ce2742df296ced6f31fe  svg-edit/editor/jgraduate/css/jgraduate.css
7315111b08a330a9c3ece3262ef4b2bc630e64b02a05d9ee5c3bd30c777042ed  svg-edit/editor/jgraduate/images/AlphaBar.png
889a9a3b55fd3b28469c7f801a8257cd7358c1b0dbbac9fc8c57ea20b1510d71  svg-edit/editor/jgraduate/images/Bars.png
53c9f67cd95713394deb5a2459bcca971aacdf7dd6eeb55c9720df0fc31f6e92  svg-edit/editor/jgraduate/images/Maps.png
adc9a1ab8598caa28be9339fb50851e0ba80995fe23af388890c701e4521eb1f  svg-edit/editor/jgraduate/images/NoColor.png
8f60ea4618604a817825d8793f2aa4fbc69b9cf894df386b2a8cf64e6c10dc47  svg-edit/editor/jgraduate/images/bar-opacity.png
bf25985affe2233dc3baa4ee59e29c1fbd7a48cf07493902d14a1ac344ed6f28  svg-edit/editor/jgraduate/images/map-opacity.png
25687420458d1f31e399b1bc5a25e95a6dce8b898ed7f9d4361ff6cb430a7c45  svg-edit/editor/jgraduate/images/mappoint.gif
29548ae674f4e396a3989b007bc4bd5d4dfcbd52640cf80f5638f72e773e14ac  svg-edit/editor/jgraduate/images/mappoint_c.png
eddc5994ff16909244d90a949ff9d7176736400e68c4dc90cfa7e3a88eccf1d2  svg-edit/editor/jgraduate/images/mappoint_f.png
3aa5592f4e753f0244866a40b9c48fced398d219b8bc5ee76d2d51f9f952c9b2  svg-edit/editor/jgraduate/images/picker.gif
cd41e45e0a93de6a6eb04fb2617ca5416f278e2c6e544294831ebf73675b97c9  svg-edit/editor/jgraduate/images/preview-opacity.png
d13aa5195095eb2e0d990d488ff4c5ed65052e6065d709463c97ed0d25cf652b  svg-edit/editor/jgraduate/images/rangearrows.gif
35d95eb6fb82f954bba0a416665a66bc95105ea1b32f664bb17868ccdeadb28c  svg-edit/editor/jgraduate/images/rangearrows2.gif
fbeb4cca71c8ef6de2c13c494ca59acf53bd174aa1ed5d7cd4cb96bd478663bc  svg-edit/editor/jgraduate/jpicker.js
ec519dac7779f36cc6eff7004181b80e91de1919fe7b7e4445b7c8ccbff8b9eb  svg-edit/editor/jgraduate/jpicker.min.js
2a39ceeb58f7a82498b3019f0edd7ece8b9b2f68cb49ac336468110ebd3d5b6e  svg-edit/editor/jgraduate/jquery.jgraduate.js
b4770307fbb619d8c0e2fa8092e0c29af54be7835bfefe498165847919648841  svg-edit/editor/jgraduate/jquery.jgraduate.min.js
e4aa82a6be912262b9aad2ad4dae070e6443c5cc35f97a34978e5d4a135d2419  svg-edit/editor/jquery-ui/jquery-ui-1.8.17.custom.min.js
48875a322a47054b96e4446298c1116876a29f1b9ff5fb9c49683bb6681f4428  svg-edit/editor/jquery-ui/jquery-ui-1.8.custom.min.js
88171413fc76dda23ab32baa17b11e4fff89141c633ece737852445f1ba6c1bd  svg-edit/editor/jquery.js
3e35670f9a819f1cd10ba82651cb0e70be80f9e537a3ddeae4905feaed496268  svg-edit/editor/jquerybbq/jquery.bbq.min.js
4ccd3b184fea32cafeb1687db6e760a945a5989897d8fa660416de301b47b282  svg-edit/editor/js-hotkeys/README.md
08b54c47b59791a61bc98f17eb8c73b331e9dd0e798e128bbcbc39631c555531  svg-edit/editor/js-hotkeys/jquery.hotkeys.min.js
31a6a7243307be24c125c73b3d976809b6dc931779151e27c26ea1916bfe9917  svg-edit/editor/locale/README.txt
edbc10357294ffcc1db05da8a01a90964885c9b36471ec6ff81f535b6eccb369  svg-edit/editor/locale/lang.af.js
fec0816bffeeb162ef162aada3c29efee936afbb81f91c6b06ea9c66df76c428  svg-edit/editor/locale/lang.ar.js
7e6f28ac9bd70d8a164eb58fc8627152fe171acf3feeef3b5d6d8ed969f81643  svg-edit/editor/locale/lang.az.js
e8610eb5a85df70309c07adfdc4db14b1a0cdea185be4ea2c051413f90a02d07  svg-edit/editor/locale/lang.be.js
570101b63ab871b1a3f814ca3ac6b3f7aaf978bae7f0e16d918289d5d997a9d3  svg-edit/editor/locale/lang.bg.js
ea68b24de5b64e3d12e69bbb8d88b8fd68b7136d2342bfcaa11c798b6497d0d9  svg-edit/editor/locale/lang.ca.js
37b8d57dc0379c72b0244c28e60641958bf867633a4a3d0be015c89558c277c8  svg-edit/editor/locale/lang.cs.js
19b7c31a03ee749e89e97a512f9f8c928bdad6c01bdc80c0d173bad07afda2e6  svg-edit/editor/locale/lang.cy.js
d51a12dfb53f7d69072326d6bfa21eabe91daf72a05e35027b596c2150283df6  svg-edit/editor/locale/lang.da.js
64f3ae3c260f1f4da01d43df1a5c6aa64c0760756531b565aceffdcaf6ed1d69  svg-edit/editor/locale/lang.de.js
88c63cca31849dc804ae3615a56d0fe8c6cdb2dedd5aa452f9f3dece005e3a80  svg-edit/editor/locale/lang.el.js
5b7bf9e2cbdfdacea8a1fa501f97c82358b89131ba5beab434da7deba5f19bd5  svg-edit/editor/locale/lang.en.js
474683d4274fb023a93a9ea84a52318d744fd2c6c0a974c78bf9f73ebcbd67c8  svg-edit/editor/locale/lang.es.js
fe5219844e7db6a62230d24c0c005511a713e5283f29595888c98f23b7d595bf  svg-edit/editor/locale/lang.et.js
2db1a6a61fbff474c8accd1a37db22a9a86dd55b65c737e1d362e15e1a6c0862  svg-edit/editor/locale/lang.fa.js
dbefbf166bd97a4c0362b6f6c2289e26cc786509fdd439407f10cdc3075cc7a0  svg-edit/editor/locale/lang.fi.js
fc6e03d484a132364364b639be0f44cad131e93d20a558a31df2a54c8968abbe  svg-edit/editor/locale/lang.fr.js
bcb3a54b08b2fbd2be089d333a74491d40d1edcd1bedb4503972e1d28b512741  svg-edit/editor/locale/lang.fy.js
ba6724dd7ed526091e9ef749a2e88770e9f041675f0a39dfb42997461174a43e  svg-edit/editor/locale/lang.ga.js
d74dc22b0369335a1f0d3fd42caac8c758e1825d1deeeb18aed4b74835149f49  svg-edit/editor/locale/lang.gl.js
6f8caa7d3acc7756c3eb50e558f4c22d6ed68c2641d5a0a9199072fdb72cac3b  svg-edit/editor/locale/lang.he.js
188b806a6637a7a26aef6ef30c1cbde53efacef143a175b3a482366f14644886  svg-edit/editor/locale/lang.hi.js
c210403f62727a0f98c95688fb1a6c0529ca0666e618ae4708497f956ab76231  svg-edit/editor/locale/lang.hr.js
721098724ba416c24e08742120186d548a9de41e52751f0d70adce8ff92a2ba9  svg-edit/editor/locale/lang.hu.js
9efb58ee084e7d9c732c6dd5377107656b10583a8f5b323ba86f863363434947  svg-edit/editor/locale/lang.hy.js
34cb54d7606d1bdb694954b6caba8f396109eeaa9c007974971e9b540eea6c96  svg-edit/editor/locale/lang.id.js
dbcb9ad375fd3bba050a772040b857e4b726ea5268b7b1db072a34b35c80fb7d  svg-edit/editor/locale/lang.is.js
4918bf05df15009785f45c0d0f3e3bb0c49379922c730601db69f6b80fb5130b  svg-edit/editor/locale/lang.it.js
9ab8297e7e1acbba52253104dd2f27c935cc5e31937d46151522ebc3c6155f7a  svg-edit/editor/locale/lang.ja.js
1f7a3ab88754516d1debc7362384744ce24ade5d14ef1b4e0108eaa3acb774b2  svg-edit/editor/locale/lang.ko.js
46cfbad2db24dd3380e9f69e0e52e638714d13bf49f49ba59a3f71284ed191d0  svg-edit/editor/locale/lang.lt.js
6b2a5ecdc3afda6925308ec325c42a1ebab4c23af32506f46695fd512e5f13c1  svg-edit/editor/locale/lang.lv.js
385bc7b41331415f3750b1149329f8ad39e515994c095ae2ec2b8d3fb2fdb070  svg-edit/editor/locale/lang.mk.js
9a8055ba616fd309e8fa6324d28fc6bb098453d698b5ac2fef2ddacd2c80e1ff  svg-edit/editor/locale/lang.ms.js
07eb91927a5fd45fc7e8ee3890b0b150ce83a1ae48da46468eabf5ff9c0de127  svg-edit/editor/locale/lang.mt.js
e132af14196e16827c6a116203fea27e49832e8f52b916d29bf4c2bb88275e76  svg-edit/editor/locale/lang.nl.js
d543c8de96a1619933dffd803f8fd26cceea78d7858ae414bd14d486663b280f  svg-edit/editor/locale/lang.no.js
ed5b954fad51f8f09276e1a536d359039cb5ef1efdd7761268f53539bd1af052  svg-edit/editor/locale/lang.pl.js
3115ec39edfff5c097619d4da1af49f7fe2474b40bc181a35f46ccc14153e869  svg-edit/editor/locale/lang.pt-BR.js
202da68f7247d1c6990a25944ef4cb51542f7e16f9ad72bce6f4b3b1fcbc101d  svg-edit/editor/locale/lang.pt-PT.js
aaed9f2057cb94a4d7ac528c18badbd039e9da3db88dd7fe1f6219c0534b3700  svg-edit/editor/locale/lang.ro.js
122dacdaac2b29da918286b7762b2f4afea76999ac7f29b211fe5bf30b53e63e  svg-edit/editor/locale/lang.ru.js
0cc9e40e0a82cce82936c0d25fe18f8d6f654389b6f53ca1e156476205c37679  svg-edit/editor/locale/lang.sk.js
a9ee613608a8f2ea2d61dc4a559e54e19263b1d2807f2694e670b593863f18be  svg-edit/editor/locale/lang.sl.js
9e659e96b2978b7f5b6a45e0a10a8e6b41b26af4d84bc9d5dcca40f8b04e2d26  svg-edit/editor/locale/lang.sq.js
316816758014de2682b6d48d4c6b7357482aa63c7a2834a45865deda39d3bc8c  svg-edit/editor/locale/lang.sr.js
a5b62585293fb1fc4dc9131bc4698596552f687d83f6d0b809288ac4e565b753  svg-edit/editor/locale/lang.sv.js
6ed9a019ace6930e3708732350d71762288b1b35ade233302fa4727d8b6236e2  svg-edit/editor/locale/lang.sw.js
3a91d656c679732f90a48ade1f80e4bfbf6f9ff2dc959bf1f11c1d1486c717f5  svg-edit/editor/locale/lang.test.js
efa4875c2dfbdacd6022955f43ce9a9e555af99b89901138510c7e8d1ba503bd  svg-edit/editor/locale/lang.th.js
c10c23f440f5a7c084462b233c785ea08c19622920cccd1988a94bd562f01662  svg-edit/editor/locale/lang.tl.js
c8e834c8551841fa91c58f796240448042fd0e7017ce2f4a9a2f2cbfd0b69c79  svg-edit/editor/locale/lang.tr.js
e3c5535a8a1ed49e0c139b3499a7c1bde79d9851068fc2b005d24a755ff68ecd  svg-edit/editor/locale/lang.uk.js
ec27f2b9b7e4e663f34c0c04ca8ddfc239ff1dbdf9ba3c6fde79c68797ef14ba  svg-edit/editor/locale/lang.vi.js
3f34f5c3b745a883cf2d5e6b3b37eacbe34f97348afcbcaae29d422c284fe941  svg-edit/editor/locale/lang.yi.js
789da54f83a00d7cdc12635b127c551f023efa57eee899347af5ac23c1d40e29  svg-edit/editor/locale/lang.zh-CN.js
ca7b32c64d5c9878538ec19ed4cbd7110cc067b5b1f014ad8dda8a7badfbf8b7  svg-edit/editor/locale/lang.zh-HK.js
475fd8d1b90e2ebd31c84099727a6b5317ab39185ab90e60c4964336ac6f3411  svg-edit/editor/locale/lang.zh-TW.js
f779b2c15f5d73de34f632d9a06a42cea6afdf71ae27edf2f098fd49a2fabd72  svg-edit/editor/locale/locale.js
8c76d9fd025bd20281fcd01d0072e3b9812924708b64a61ce4b6b567d68163bf  svg-edit/editor/math.js
7bb3443556a8632cbe2710ca84ddd595f7f21e3771ca7eeb71744e4ee2e3014c  svg-edit/editor/path.js
964e1c6bef7467e8a0d95dea5fa395dc9aa8a18648c929bb97c747335753ac5e  svg-edit/editor/sanitize.js
e691d97052dff8bc2be734f557eacd461a03c54262a57dbb7eeac7aac80e0234  svg-edit/editor/select.js
8154b1a9a931b3ee5d89b103aa343ec85c8a7555cd2e670c5c452e4643c7f4e5  svg-edit/editor/spinbtn/JQuerySpinBtn.css
1019acc1505be807c5f3497debb3c562737391a2a6dcba43d66de4a5671ad7d9  svg-edit/editor/spinbtn/JQuerySpinBtn.js
2375545631effb6ff0cc6b5e657ba2c90b7071a57ae727d93288ba69c30b3e64  svg-edit/editor/spinbtn/JQuerySpinBtn.min.js
d2317a6d3707925583a7428a457ab8971660d95eff36ebb988a6e66f3845c5af  svg-edit/editor/spinbtn/spinbtn_updn.png
a135b5b12be48070eb64acbe017f99ca48c5f87263fee4e5317286069af805cc  svg-edit/editor/svg-editor.css
22a3b25ff821a94e2e46022943d4286d60638897f8009de906bf127b1a6a0ebe  svg-edit/editor/svg-editor.html
f08b71e0604835e05aec87369b914b91df7ea823ba109c9cfbb8a869a8cda02f  svg-edit/editor/svg-editor.js
ab3e359410550c0192a612f1c2ce018676767a67eec77549a835a57a6b9a1c2b  svg-edit/editor/svg-editor.manifest
04dc35af010666ac8a939cf285d6f24e50960424d6435ba9e0a6b2cc14141b2c  svg-edit/editor/svgcanvas.js
0c6aab42b013b9f48114a6358de3e0b5f18d0658eb801de21636e1db0e68cfc4  svg-edit/editor/svgedit.compiled.js
2c1fa2dcf5bb8c2144fe419536daebf718fa03b33a2fcd700bcd7c0ea049141b  svg-edit/editor/svgicons/jquery.svgicons.js
c62b98d3e6821c74087a2ce0ffce0b4c574c23d58b2e000309925881775cc148  svg-edit/editor/svgtransformlist.js
1590a0f85f60675773eb9987538c93c3a3d4946cf19fcc6d870b5f8274ec2842  svg-edit/editor/svgutils.js
4329fe02f88a10fbc7f531a992f5d1950a0146fe1a818d64b2f333bf7d3b56c7  svg-edit/editor/touch.js
f9c476a036034876125c3b5e22db026547c2bcc80442feffc423419ac07e7340  svg-edit/editor/units.js
e22efa0762ef2893469fa5fa1dcfe6ebb28f05cb756c6f56e8c35ce7748cb02d  template.py
611ae387223cf2513d3b15676ea86a2def249b9657d099745d70ab5377195872  utils.py
b5d330e1effa8775b0950b90695716c9a77d8056895e11cde59e385ca904856c  web.py
616a970077edef2c7596c7114bbac2883c1731297fedf50ec3d448422ad1398c  web/editor.css
b05e7f75220d38c20ee58e75cff7dfe23e9ae755b7014e2f3cd5228124ee5349  web/editor.js
260ab7b64f63d25e92b9a12ef479d68e7eb8998c5b256b39ed36d2a8616b8388  web/reviewer.js
```
