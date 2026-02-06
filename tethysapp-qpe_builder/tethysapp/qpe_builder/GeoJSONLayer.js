import { h, render } from "https://unpkg.com/preact?module";
import htm from "https://unpkg.com/htm?module";

export function GeoJSONLayer(props) {

}


export function bind(node, config) {
	return {
		create: (component, props, children) => h(component, props, ...children),
		render: (element) => render(element, node),
		unmount: () => render(null, node),
	};
}