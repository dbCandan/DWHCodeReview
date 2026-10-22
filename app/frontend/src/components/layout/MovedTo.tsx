import {Navigate, useLocation} from 'react-router';

/** An address from an earlier layout; keeps links and bookmarks working by sending them on. */
export function MovedTo({to}: {to: string}) {
  const {search} = useLocation();
  return <Navigate to={{pathname: to, search}} replace />;
}
