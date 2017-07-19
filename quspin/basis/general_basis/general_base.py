import numpy as _np
import scipy.sparse as _sp
from ..lattice import lattice_basis


def process_map(map,q):
	map = _np.asarray(map,dtype=_np.int32)
	i_map = map.copy()
	i_map[map<0] = -(i_map[map<0] + 1) # site mapping
	s_map = map < 0 # sites with spin-inversion

	sites = _np.arange(len(map),dtype=_np.int32)
	order = sites.copy()

	if _np.any(_np.sort(i_map)-order):
		raise ValueError("map must be a one-to-one site mapping.")

	per = 0
	while(True):
		sites[s_map] = -(sites[s_map]+1)
		sites = sites[i_map]
		per += 1

		if not _np.any(sites - order):
			break

	# becaise of the cyclic nature of the mapping
	# map^(-1) is just map^(per-1)

	# apply the mapping per-1 times to get the inverse mapping
	rev_map = order.copy()
	for i in range(per-1):
		rev_map[s_map] = -(rev_map[s_map] + 1)
		rev_map = rev_map[i_map]

	return map,rev_map,per,q


class general_basis(lattice_basis):
	def __init__(self,N,**kwargs):
		self._unique_me = True
		self._check_symm = None
		self._check_pcon = None

		if self.__class__ is general_basis:
			raise TypeError("general_basis class is not to be instantiated.")

		kwargs = {key:value for key,value in kwargs.items() if value is not None}
		
		if not kwargs:
			raise ValueError("require at least one map.")

		n_maps = len(kwargs)


		if any((type(map) is not tuple) and (len(map)!=2) for map in kwargs.values()):
			raise ValueError("blocks must contain tuple: (map,q).")

		
		kwargs = {block:process_map(*item) for block,item in kwargs.items()}

		sorted_items = sorted(kwargs.items(),key=lambda x:x[1][2])
		sorted_items.reverse()

		self._blocks = {block:((-1)**q if per==2 else q) for block,(_,_,per,q) in sorted_items}

		blocks,items = zip(*sorted_items)
		maps,rev_maps,pers,qs = zip(*items)

		self._maps = _np.vstack(maps)
		self._rev_maps = _np.vstack(rev_maps)
		self._qs   = _np.asarray(qs,dtype=_np.int32)
		self._pers = _np.asarray(pers,dtype=_np.int32)

		if any(map.ndim != 1 for map in self._maps[:]):
			raise ValueError("maps must be a 1-dim array/list of integers.")

		if any(map.shape[0] != N for map in self._maps[:]):
			raise ValueError("size of map is not equal to N.")

		if self._maps.shape[0] != self._qs.shape[0]:
			raise ValueError("number of maps must be the same as the number of quantum numbers provided.")

		for j in range(n_maps-1):
			for i in range(j+1,n_maps,1):
				if _np.all(self._maps[j]==self._maps[i]):
					ValueError("repeated map in maps list.")

	@property
	def blocks(self):
		return self._blocks

	@property
	def N(self):
		return self._N

	@property
	def sps(self):
		return self._sps

	@property
	def Ns(self):
		return self._Ns

	def append(self,other):
		if self.__class__ != other.__class__:
			raise ValueError

	def Op(self,opstr,indx,J,dtype):
		indx = _np.asarray(indx,dtype=_np.int32)

		if len(opstr) != len(indx):
			raise ValueError('length of opstr does not match length of indx')

		if _np.any(indx >= self._N) or _np.any(indx < 0):
			raise ValueError('values in indx falls outside of system')

		extra_ops = set(opstr) - self._allowed_ops
		if extra_ops:
			raise ValueError("unrecognized characters {} in operator string.".format(extra_ops))

		if self._Ns <= 0:
			return _np.array([],dtype=dtype),_np.array([],dtype=self._index_type),_np.array([],dtype=self._index_type)
	
		col = _np.zeros(self._Ns,dtype=self._index_type)
		row = _np.zeros(self._Ns,dtype=self._index_type)
		ME = _np.zeros(self._Ns,dtype=dtype)

		self._core.op(row,col,ME,opstr,indx,J,self._basis,self._n)

		mask = _np.logical_not(_np.logical_or(_np.isnan(ME),_np.abs(ME)==0.0))
		col = col[mask]
		row = row[mask]
		ME = ME[mask]

		return ME,row,col	

	def get_norms(self):
		return _np.sqrt(self._n)

	def get_proj(self,dtype):
		c = _np.ones_like(self._basis,dtype=dtype)
		c[:] = self._n[:]
		_np.sqrt(c,out=c)
		_np.power(c,-1,out=c)
		index_type = _np.min_scalar_type(-(self._sps**self._N))
		col = _np.arange(self._Ns,dtype=index_type)
		row = _np.arange(self._Ns,dtype=index_type)
		return self._core.get_proj(self._basis,dtype,c,row,col)

	def get_vec(self,v_in,sparse=True):
		if not hasattr(v_in,"shape"):
			v_in = _np.asanyarray(v_in)

		squeeze = False

		if v_in.ndim == 1:
			shape = (self._sps**self._N,1)
			v_in = v_in.reshape((-1,1))
			squeeze = True
		elif v_in.ndim == 2:
			shape = (self._sps**self._N,v_in.shape[1])
		else:
			raise ValueError("excpecting v_in to have ndim at most 2")

		if self._Ns <= 0:
			if sparse:
				return _sp.csr_matrix(([],([],[])),shape=(self._sps**self._N,0),dtype=v_in.dtype)
			else:
				return _np.zeros((self._sps**self._N,0),dtype=v_in.dtype)

		if v_in.shape[0] != self._Ns:
			raise ValueError("v_in shape {0} not compatible with Ns={1}".format(v_in.shape,self._Ns))

		if _sp.issparse(v_in): # current work around for sparse states.
			# return self.get_proj(v_in.dtype).dot(v_in)
			raise ValueError

		if not v_in.flags["C_CONTIGUOUS"]:
			v_in = _np.ascontiguousarray(v_in)

		if sparse:
			# current work-around for sparse
			return self.get_proj(v_in.dtype).dot(_sp.csr_matrix(v_in))
		else:
			v_out = _np.zeros(shape,dtype=v_in.dtype,)
			self._core.get_vec_dense(self._basis,self._n,v_in,v_out)
			if squeeze:
				return  _np.squeeze(v_out)
			else:
				return v_out	
