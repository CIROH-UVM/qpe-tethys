// Greeting.jsx

// Import React (optional in newer React versions, but a common practice)
import { h, render } from "https://unpkg.com/preact?module";
import htm from "https://unpkg.com/htm?module";

const html = htm.bind(h);

/**
 * A functional component that accepts a 'name' prop.
 */
// const Greeting = ({ name }) => {
//   return (
//     <h2>Hello, {name}!</h2>
//   );
// };

export function Greeting(props) {
  return html`<h2>Hello, ${props.name}!</h2>`;
}

// Export the component for use in other files
// export default Greeting;

export function bind(node, config) {
	return {
		create: (component, props, children) => h(component, props, ...children),
		render: (element) => render(element, node),
		unmount: () => render(null, node),
	};
}