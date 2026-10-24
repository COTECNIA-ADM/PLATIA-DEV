// Logo comercial de PLATIA (barra lateral, inicio de sesión y acceso denegado).
// Decorativo: el nombre "PLATIA" va siempre al lado en texto.
import logo from '../assets/logo.png'

export default function BrandMark() {
  return <img className="brand-mark" src={logo} alt="" width={30} height={30} />
}
