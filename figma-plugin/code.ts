// Maths SVG Importer — Figma Plugin
// Receives SVG strings from the UI and creates editable Figma vector nodes.

figma.showUI(__html__, { width: 480, height: 560 });

figma.ui.onmessage = async (msg: {
  type: string;
  svgContent?: string;
  name?: string;
  svgList?: Array<{ name: string; svg: string }>;
}) => {
  if (msg.type === "import-single") {
    await importSingle(msg.svgContent || "", msg.name || "Maths Diagram");
  } else if (msg.type === "import-batch") {
    await importBatch(msg.svgList || []);
  } else if (msg.type === "cancel") {
    figma.closePlugin();
  }
};

async function importSingle(svgContent: string, name: string) {
  try {
    const node = figma.createNodeFromSvg(svgContent);
    node.name = name;

    // Position at center of viewport
    const viewport = figma.viewport.center;
    node.x = viewport.x - node.width / 2;
    node.y = viewport.y - node.height / 2;

    figma.currentPage.selection = [node];
    figma.viewport.scrollAndZoomIntoView([node]);

    figma.ui.postMessage({
      type: "success",
      message: `Imported "${name}" (${node.width}×${node.height})`,
    });
  } catch (error: any) {
    figma.ui.postMessage({
      type: "error",
      message: `Failed to import: ${error.message || error}`,
    });
  }
}

async function importBatch(svgList: Array<{ name: string; svg: string }>) {
  const padding = 40;
  let xOffset = 0;
  const importedNodes: SceneNode[] = [];
  const results: string[] = [];

  // Create a frame to hold all imports
  const frame = figma.createFrame();
  frame.name = "Maths SVG Import Batch";
  frame.layoutMode = "HORIZONTAL";
  frame.itemSpacing = padding;
  frame.paddingLeft = padding;
  frame.paddingRight = padding;
  frame.paddingTop = padding;
  frame.paddingBottom = padding;
  frame.primaryAxisSizingMode = "AUTO";
  frame.counterAxisSizingMode = "AUTO";
  frame.fills = [{ type: "SOLID", color: { r: 1, g: 1, b: 1 } }];

  for (const item of svgList) {
    try {
      const node = figma.createNodeFromSvg(item.svg);
      node.name = item.name;
      frame.appendChild(node);
      importedNodes.push(node);
      results.push(`OK: ${item.name}`);
    } catch (error: any) {
      results.push(`FAIL: ${item.name} — ${error.message || error}`);
    }
  }

  // Position frame at viewport center
  const viewport = figma.viewport.center;
  frame.x = viewport.x - frame.width / 2;
  frame.y = viewport.y - frame.height / 2;

  figma.currentPage.selection = [frame];
  figma.viewport.scrollAndZoomIntoView([frame]);

  figma.ui.postMessage({
    type: "batch-complete",
    message: `Imported ${importedNodes.length}/${svgList.length} diagrams`,
    details: results,
  });
}
