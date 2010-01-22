import numpy as N
import theano
import theano.tensor as T
from theano import gof, Op, tensor, config
from theano.printing import Print

def getFilterOutShp(inshp, kshp, (dx,dy)=(1,1), mode='valid'):
    """Returns numpy ndarray of len 2
    """
    if mode=='valid': s = -1
    else: s = 1
    inshp, kshp = N.array(inshp), N.array(kshp)
    return  N.int64(N.ceil((inshp[1:] + s*kshp - s*1)/\
            N.array([dx,dy], dtype='float')))


def conv2d(input, filters, border_mode='valid', subsample=(1,1), 
           image_shape=None, filter_shape=None, **kargs):
    """
    This function returns an instanciated ConvOp through a simple interface.
    We do this instead of changing the ConvOp interface so as not to change 
    previous code based on the ConvOp.

    :type input: symbolic 4D tensor
    :param input: tensor containing mini-batch of input feature maps that are 
    2D. Indexing is thus: (batch, feature map, image row, image col).
    :type filters: symbolic 4D tensor
    :param filters: tensor containing filters for convolutional neural net.
    Indexing is: (filter, filter input feature map, filter row, filter col).
    :type border_mode: string
    :param border_mode:'valid'(only apply kernel over complete patch of the image)
                       or 'full'(padd the image with 0 and apply the kernel over all full patch and partial patch of the image
    :type subsample: tuple of len 2
    :param subsample: how many pixel we move in the (row,col) direction of the image when we change of patch
    :type image_shape: tuple of len 4
    :param image_shape: (batch size, stack size, nb row, nb col)
    :type filter_shape: tuple of len 4
    :param filter_shape: (nb kernel, stack size, nb row, nb col)
    """
    if image_shape and filter_shape:
        assert image_shape[1]==filter_shape[1]

    if filter_shape is not None:
        nkern = filter_shape[0]
        kshp = filter_shape[2:]
    else:
        nkern, kshp = None, None

    if image_shape is not None:
        bsize = image_shape[0]
        imshp = image_shape[1:]
    else:
        bsize, imshp = None, None

    print 'imshp = ', imshp
    print 'kshp = ', kshp
    print 'nkern = ', nkern
    print 'bsize = ', bsize

    op = ConvOp(output_mode=border_mode, dx=subsample[0], dy=subsample[1],
                imshp=imshp, kshp=kshp, nkern=nkern, bsize=bsize,**kargs)

    return op(input, filters)


class ConvOp(Op):
    """
    A convolution op that should extend scipy.signal.convolve2d, but much faster!
    """


    
    __attrnames = ['imshp', 'kshp', 'nkern', 'bsize', 'dx', 'dy', 'out_mode', 
            'unroll_batch', 'unroll_kern', 'unroll_patch',
            'imshp_logical', 'kshp_logical', 'kshp_logical_top_aligned']
    """These attributes uniquely identify the behaviour of this op for given inputs"""

    def __init__(self, imshp=None, kshp=None, nkern=None, bsize=None, dx=None, dy=None, output_mode='valid',
            unroll_batch=0,
            unroll_kern=0,
            unroll_patch=True,
            imshp_logical=None,
            kshp_logical=None,
            kshp_logical_top_aligned=True,
            verbose=0,
            version=-1):
        """
        This Op implement the convolution of a kernel(tensor 4d,(nkern, stacksize, nb row, nb col)) on an image(tensor 4d, (batchsize, stacksize, nb row, nb col). The batch size is multiple image that we want to apply the same kernel over. The nkern is numtiple kernel that we want to apply to each image. The stack size is mostly used when their is multiple layer in the network. It is the sum of the convolution of multiple 2d image and kernel.

        The reason that this op does the summation over convolutions within the 'stack' is that
        it allows us to be memory-efficient about how gradients are calculated.  If, for
        example, we had a convolution op that took a list of images, a list of kernels, and
        gave you back each image as filtered by each kernel (JB thought he wanted this at one
        point) then we would have to sum over a potentially very large tensor to get the
        gradient on the filters.


        If the imshp, kshp, nkern and bsize are provided, we can generate more optimal code. This make a significant difference for the full mode with unroll_patch version.
        The most frequent faster code currently available on 64_x86 computer is unroll_batch=4, unroll_kern=4, unroll_patch=False and this request that all the optional shape information are gived. Those number are empirically tested and backed up by the article: Anatomy of High-Performance Matrix Multiplication by Kazushige Goto and Robert A. Van De Geijn, ACM Transactions on Mathematical Software, vol 34, No. 3, article 12, May 2008. It is in figure 12, it give the value mr x nr, those value are the optimum to use for unroll_batch and unroll_kern. For x86_64 bits computer it is 4x4. Other architecture can have different value.(2x4 for x86, 8x8 for itanium,...)

        :type out_mode: string
        :param out_mode: 'valid'(give an output smaller then the image, 'full'(give an output bigger then the image)

        optional parameter(if provided will be used to generate more optinal c code):
        
        :type imshp: tuple of len 2 or 3: 2 for 2d image, 3 for a stack of 2d images.
        :param imshp: (stacksize, nb image row, nb image col)
        :type kshp: tuple of len 2
        :param kshp: (nb kernel row, nb kernel col)
        :type nkern: int
        :param nkern: the number of kernel
        :type bsize: int
        :param bsize: the size of the minibatch
        :type dx: int
        :param dx: patch stride rows
        :type dy: int
        :param dx: patch stride cols

        param to select the version of code used:
        :type unroll_patch: bool
        :param unroll_patch: use a version of c_code that unroll the patch loop that don't request all shape information to work, but if all shape information are present, will use it to hardcode the value in the code for faster code.

        :type unroll_batch:int
        :param unroll_batch: use a version of c_code that unroll the batch(by unroll_batch) and the nkern(by unroll_kern) loop. The size must by a multiple of bsize or nkern respectively.
        :type unroll_kern:int
        :param unroll_kern: use a version of c_code that unroll the batch(by unroll_batch) and the nkern(by unroll_kern) loop. The size must by a multiple of bsize or nkern respectively.

        :type verbose: int
        :param verbose: passed to GpuConv
        :type version: int
        :param version: passed to GpuConv

        :param imshp_logical: used internally when we generate the gradient when dx!=1 or dy!=1
        :param kshp_logical: idem
        :param kshp_logical_top_aligned: idem
        
        """
        all_shape = imshp is not None and kshp is not None and nkern is not None and bsize is not None
        if (unroll_batch>0 or unroll_kern>0) and not all_shape:
            raise Exception("In ConvOp, when using unroll_batch and unroll_nkern, all shape are needed")
        if not all_shape and (imshp is not None or kshp is not None or nkern is not None or bsize is not None):
            print "OPTIMISATION WARNING: passing only a few shape to ConvOp for faster code is useless. We use all of them or none."
        
        if not all_shape:
            unroll_patch = True

        if imshp is not None:
            imshp = tuple(imshp)
            if len(imshp)==2:
                imshp = (1,)+imshp
            elif len(imshp)==3:
                imshp = imshp
            else:
                raise Exception("bad len for imshp")
        self.imshp = imshp
        if kshp is not None:
            kshp = tuple(kshp)
        self.kshp = kshp
        self.nkern = nkern
        self.bsize=bsize
        self.dx=dx
        self.dy=dy
        self.verbose=verbose
        self.version=version
        # a triple
        self.imshp_logical = self.imshp
        if imshp_logical is not None: self.imshp_logical = tuple(imshp_logical)
        assert (self.imshp is None and self.imshp_logical is None) or (len(self.imshp) == len(self.imshp_logical))

        # a pair
        self.kshp_logical = self.kshp
        if kshp_logical is not None: self.kshp_logical = tuple(kshp_logical)
        self.kshp_logical_top_aligned = kshp_logical_top_aligned

        self.unroll_batch=unroll_batch
        self.unroll_kern=unroll_kern
        self.unroll_patch=unroll_patch

        if self.unroll_batch>0 and self.bsize % self.unroll_batch!=0:
            if self.bsize<=self.unroll_batch:
                self.unroll_batch = self.bsize
            else:
                #find the maximum value under unroll_batch that would work
                new=self.unroll_batch
                assert(new>=1)
                while self.bsize % new!=0:
                    new-=1

                print "OPTIMISATION WARNING: in ConvOp.__init__() unroll_batch(%s) must be 0 or a divisor of bsize(%s). We revert it to %d. This won't change the result, but may make it slower."%(str(self.unroll_batch),str(self.bsize),new)
                self.unroll_batch=new
        if self.unroll_kern>0 and self.nkern % unroll_kern!=0:
            if self.nkern<=self.unroll_kern:
                self.unroll_kern = self.nkern
            else:
                #find the maximum value under unroll_kern that would work
                new=self.unroll_kern
                assert(new>=1)
                while self.nkern % new!=0:
                    new-=1
                print "OPTIMISATION WARNING: in ConvOp.__init__() unroll_kern(%s) should be 0 or a divisor of nkern(%s)We revert it to %d. This won't change the result, but may make it slower."%(str(self.unroll_kern),str(self.nkern),new)
                self.unroll_kern=new
        if all_shape:
            self.outshp = getFilterOutShp(self.imshp_logical, self.kshp_logical, (dx,dy), output_mode)
            self.fulloutshp = getFilterOutShp(self.imshp_logical, self.kshp_logical, (1,1), output_mode)
        else:
            self.outshp = None
            self.fulloutshp = None
        self.out_mode = output_mode
        if not self.out_mode in ["valid", "full"]:
            raise Exception("Mode %s not implemented"%self.out_mode)
       
        if all_shape and not (self.outshp > 0).all():
            raise Exception(("Bad size for the output shape. Verify that [post-supersampling] input shape (%s)"
                "and kern shape(%s) are ok. (hint: kerns must fit inside image in"
                "'valid' mode)")%(self.imshp_logical,self.kshp_logical))

        self._rehash()
        if config.config.getboolean('op.set_flops'):
            self.set_flops()

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        for a in self.__attrnames:
            if getattr(self, a) != getattr(other, a):
                return False
        return True

    def __setstate__(self, d):
        self.__dict__.update(d)
        self._rehash()

    def _rehash(self):
        hashval = hash(type(self))
        for a in self.__attrnames:
            hashval = hashval ^ hash(getattr(self, a))
        self.__hashval = hashval

    def __hash__(self):
        return self.__hashval

    def __str__(self):
        return "ConvOp{" +",".join(str((a, getattr(self, a))) for a in self.__attrnames)  + "}"

    def set_flops(self):
        """ Usefull with the hack in profilemode to print the MFlops"""
        if self.out_mode=="valid":
            self.flops=self.kshp[0]*self.kshp[1]*2#nb mul and add by output pixed
            self.flops*=self.outshp[0]*self.outshp[1]#nb flops by output image
            self.flops*=self.imshp[0]*self.nkern*self.bsize#for all outputs images#n_stack==self.imshp[0]
        else: #full mode not implemented
            self.flops=0
            for out_row in range(self.outshp[0]):#loop over output row
                for out_col in range(self.outshp[0]):#loop over output col
                    for row in range(self.kshp[0]):#loop over kern row
                        if row+out_row-self.kshp[0]+1<0 or row+out_row-self.kshp[0]+1>=self.imshp[1]: continue
                        col=0
                        max_col=self.kshp[1]
                        img_col=out_col-self.kshp[1]+1
                        max_col=min(max_col,self.imshp[2]-img_col)

                        if img_col<0:
                            col=-img_col
                            img_col+=col
                        while col < max_col: #loop over kern col
                            self.flops+=2
                            col+=1
            
            self.flops*=self.imshp[0]*self.nkern*self.bsize#for all outputs images#n_stack==self.imshp[0]
            
            assert self.flops==self.bsize * self.nkern * self.imshp[0] * self.kshp[0] * self.kshp[1] * self.imshp[1] * self.imshp[2] * 2

    def make_node(self, inputs, kerns):
        # TODO: find a way to make ConvOp work for N-D (after NIPS09)
        """
        inputs - 4 dim: batches x stacksize x rows x cols
        kerns - 4 dim: nkern x stackidx x rows x cols
        """
        outdim = kerns.ndim
        _inputs = tensor.as_tensor_variable(inputs)
        _kerns = tensor.as_tensor_variable(kerns)
        # TODO: lift this restriction by upcasting either inputs or kerns
        if _inputs.ndim != 4:
            raise TypeError('make_node requires 4D tensor of inputs')
        if _kerns.ndim != 4:
            raise TypeError('make_node requires 4D tensor of kernels')
        if _inputs.type.dtype != _kerns.type.dtype:
            raise NotImplementedError("The image and the kernel must have the same type."
                            "inputs(%s), kerns(%s)"%(_inputs.dtype, _kerns.dtype))
        output = tensor.tensor(dtype=_inputs.type.dtype,
                               broadcastable=[_inputs.broadcastable[0],
                                   _kerns.broadcastable[0], False, False]); 

        return gof.Apply(self, [_inputs, _kerns], [output])

    def perform(self,node, (img2d, filtersflipped), (z,)):
        """
        By default if len(img2d.shape)==3, we
        """
        # TODO: move these back out to global scope when they no longer cause an atexit error
        from scipy.signal.signaltools import  _valfrommode, _bvalfromboundary
        from scipy.signal.sigtools import _convolve2d
        imshp = self.imshp
        if imshp is None:
            imshp = tuple(img2d.shape[1:])
        kshp = self.kshp
        if kshp is None:
            kshp = tuple(filtersflipped.shape[2:])
        bsize = self.bsize
        if bsize is None:
            bsize = img2d.shape[0]
        nkern = self.nkern
        if nkern is None:
            nkern = filtersflipped.shape[0]
        
        imshp_logical = self.imshp_logical
        if imshp_logical is None:
            imshp_logical = imshp
        kshp_logical = self.kshp_logical
        if kshp_logical is None:
            kshp_logical = kshp
            
        if self.fulloutshp is not None:
            fulloutshp = tuple(self.fulloutshp)
        else:
            fulloutshp = tuple(getFilterOutShp(imshp_logical, kshp_logical, (1,1), self.out_mode))

        if z[0] is None:
            z[0] = N.zeros((bsize,)+(nkern,)+fulloutshp,
                           dtype=img2d.dtype)
        zz=z[0]
        val = _valfrommode(self.out_mode)
        bval = _bvalfromboundary('fill')

        stacklen = imshp[0]

        img2d = img2d.reshape((bsize,)+ imshp)
        filtersflipped = filtersflipped.reshape((nkern,stacklen)+kshp)

        if self.imshp != self.imshp_logical:
            # assuming that to get from imshp to imshp logical we insert zeros in missing spots
            rstride = int(N.ceil(imshp_logical[1] / float(imshp[1])))
            cstride = int(N.ceil(imshp_logical[2] / float(imshp[2])))
            buf = N.zeros((bsize,)+ imshp_logical, dtype=img2d.dtype)
            buf[:,:,::rstride, ::cstride] = img2d
            img2d = buf
            del buf, rstride, cstride

        if kshp != kshp_logical:
            rstride = int(N.ceil(kshp_logical[0] / float(kshp[0])))
            cstride = int(N.ceil(kshp_logical[1] / float(kshp[1])))
            buf = N.zeros((nkern,stacklen)+ self.kshp_logical, dtype=filtersflipped.dtype)
            if self.kshp_logical_top_aligned:
                roffset=coffset=0
            else:
                roffset=(kshp_logical[0] - (kshp[0]*rstride) - 1+rstride) % rstride
                coffset=(kshp_logical[1] - (kshp[1]*cstride) - 1+cstride) % cstride
                assert roffset >= 0
                assert coffset >= 0
            buf[:,:,roffset::rstride, coffset::cstride] = filtersflipped
            filtersflipped = buf
            del buf, rstride, cstride

        for b in range(bsize):
            for n in range(nkern):
                zz[b,n,...].fill(0)
                for im0 in range(stacklen):
                    zz[b,n,...] +=  _convolve2d(\
                        img2d[b,im0,...], filtersflipped[n,im0,...],1,val, bval, 0)
        #We copy it to remove the Stride mismatch warning from DEBUG_MODE.
        #The copy make that we return an object with the same stride as the c version.
        #The copy don't affect the performence during our experience as in that case we
        #execute the c version which is much faster.
        if self.dx>1 or self.dy>1:
            zz = zz[:,:,0::self.dx,0::self.dy].copy()

        z[0]=zz


    def grad(self, (inputs, kerns), (gz,)):
        """
        In development. Works for test cases in test_sp.py
        A few known issues:
        * doesn't work for rectangular images or filters
        * inputs needs to be a 4D tensor. Couldn't get 3D to work
        * will crash if filter the same size as input image
        """
        if self.imshp != self.imshp_logical or self.kshp != self.kshp_logical:
            raise NotImplementedError('todo')

        if self.dx!=1 or self.dy!=1:
            raise Exception("ERROR: We disable ConvOp.grad now when dx!=1 or dy!=1 as we think their is a high probability of bug in it. We need to raise the error on the gradient to .1!")

        all_shape = self.imshp is not None and self.kshp is not None and self.nkern is not None and self.bsize is not None

        if not all_shape and (self.dx!=1 or self.dy!=1):
            raise Exception("ConvOp.grad when dx!=1 or dy!=1 we must have all the optional shape information")
        
        grad_hack_necessary = False
        if grad_hack_necessary:
            if self.dx!=1 or self.dy!=1:
                upgz = T.as_tensor(N.zeros((self.bsize,self.nkern)+tuple(self.fulloutshp),
                                           dtype=gz.type.dtype))
                gz = T.SetSubtensor([slice(self.bsize), slice(self.nkern),
                                     slice(0,self.fulloutshp[0],self.dy),
                                     slice(0,self.fulloutshp[1],self.dx)])(upgz,gz)

        ####### Determine gradient on kernels ########
        assert inputs.ndim==4 and kerns.ndim==4

        newin = inputs.dimshuffle((1,0,2,3))
        newgz = gz.dimshuffle((1,0,2,3))
    
        (bsize, nkern) = None, None
        imshp = None
        kshp = None
        un_p = self.unroll_patch
        imshp_logical = None
        if self.out_mode == 'valid':
            (img, filters) = (newin, newgz)
            kshp_logical = self.fulloutshp
            kshp_logical_top_aligned=False
            if all_shape:
                (bsize, nkern) = (self.imshp[0], self.nkern)
                imshp = (self.bsize, self.imshp[1], self.imshp[2])
            kshp  = self.outshp
            un_b = self.unroll_batch
            un_k = self.unroll_kern
            #print 'dw_valid', imshp, kshp, nkern, bsize
        elif self.out_mode == 'full':
            (img, filters) = (newgz, newin)
            kshp_logical = None
            kshp_logical_top_aligned=True
            if all_shape:
                imshp_logical = (self.bsize, self.fulloutshp[0], self.fulloutshp[1])
                (bsize, nkern) = (self.nkern, self.imshp[0])
                imshp = (self.bsize, self.outshp[0], self.outshp[1])
                kshp  = self.imshp[1:]
            un_b = self.unroll_kern
            un_k = self.unroll_batch
            #print 'dw_full', imshp, kshp, nkern, bsize
        else:
            raise NotImplementedError('Only [full,valid] modes are currently supported.')

        filters = filters[:,:,::-1,::-1] #flip them
        
        #find good value for the unroll
        if all_shape and un_b!=0 and bsize%un_b!=0:
            if bsize<un_b:
                un_b = bsize
            else:
                un_b = 1
                print "OPTIMISATION WARNING: in ConvOp.grad() we can't determine a good unroll value for the batch. Maybe you can optimize this!", bsize, un_b, self.unroll_batch, self.unroll_kern
        if un_k!=0 and nkern%un_k!=0:
            if nkern<un_k:
                un_k = nkern
            else:
                un_k = 1
                print "OPTIMISATION WARNING: in ConvOp.grad() we can't determine a good unroll value for the kernel. Maybe you can optimize this!"

        dw = ConvOp(imshp, kshp, nkern, bsize, 1,1, output_mode='valid',
                    unroll_batch=un_b, unroll_kern=un_k, unroll_patch=un_p,
                    imshp_logical=imshp_logical,
                    kshp_logical=kshp_logical,
                    kshp_logical_top_aligned=kshp_logical_top_aligned,
                    version=self.version,
                    verbose=self.verbose)
        if hasattr(self,'flops'):
            dw.set_flops()
        dw = dw(img,filters)
        if all_shape:
            assert (dw.owner.op.outshp==self.kshp).all()
        if self.out_mode == 'valid':
            # before DimShuffle, dw is of shape visdim x nkern x kshp[0] x kshp[1]
            dw = dw.dimshuffle((1,0,2,3))
            dw = dw[:,:,::-1,::-1]

        ####### Determine gradient on inputs ########
        mode = 'valid'
        if not self.out_mode == 'full': mode = 'full'
        filters = kerns.dimshuffle((1,0,2,3))
        filters = filters[:,:,::-1,::-1]
        nkern = None
        imshp = None
        imshp_logical = None
        kshp = None
        if all_shape:
            nkern = self.imshp[0]
            imshp = (self.nkern, self.outshp[0], self.outshp[1])
            imshp_logical=(self.nkern, self.fulloutshp[0], self.fulloutshp[1])
        #print 'din', imshp, self.kshp, nkern
        din = ConvOp(imshp, self.kshp, nkern, self.bsize, 
                     1,1, output_mode=mode,
                     unroll_batch=un_b, unroll_kern=un_k, unroll_patch=un_p,
                     imshp_logical=imshp_logical,
                     kshp_logical=None,
                     version=-1,#we we change the mode, we don't forward the version.
                     verbose=self.verbose)
        if hasattr(self,'flops'):
            din.set_flops()
        din = din(gz,filters)
        assert (din.owner.op.outshp is None and self.imshp is None) or (din.owner.op.outshp==self.imshp[1:]).all()
        return [din, dw]

    def c_headers(self):
        return ['<numpy/noprefix.h>', '<iostream>', '<sstream>' ]

    def c_code_cache_version(self):
        return (1)
    
    def c_support_code(self):
        return """
#define STRIDES(arr) ((arr)->strides)
#define FULL  2
#define SAME  1
#define VALID 0
#define MOD %
using namespace std;
""" + tensor.blas.blas_header_text()
    def c_libraries(self):
        return tensor.blas.ldflags()
    def c_code(self, node, name, (img2d, filtersflipped), (z, ), sub):
        if node.inputs[0].type.dtype != node.inputs[1].type.dtype:
            raise NotImplementedError()
        assert node.inputs[0].type.dtype == node.inputs[1].type.dtype
        d=locals()
        d.update(sub)

        all_shape = self.imshp is not None and self.kshp is not None and self.nkern is not None and self.bsize is not None

        d["self_out_mode"]=self.out_mode
        d["self_dx"]=self.dx
        d["self_dy"]=self.dy
        d["mode"]=self.out_mode.upper()
        d["mode"]=self.out_mode.upper()
        d["affectation"]="="
        if all_shape:
            d["self_bsize"]=self.bsize
            d["self_nkern"]=self.nkern
            d["self_outshp0"]=self.outshp[0]
            d["self_outshp1"]=self.outshp[1]
            d["self_imshp0"]=self.imshp[0]
            d["self_imshp1"]=self.imshp[1]
            d["self_imshp2"]=self.imshp[2]
            d["self_kshp0"]=self.kshp[0]
            d["self_kshp1"]=self.kshp[1]
            d["self_kshp_logical_r"] = self.kshp_logical[0]
            d["self_kshp_logical_c"] = self.kshp_logical[1]
            d["self_kshp_logical_stride_r"] = int(N.ceil(self.kshp_logical[0] / float(self.kshp[0])))
            d["self_kshp_logical_stride_c"] = int(N.ceil(self.kshp_logical[1] / float(self.kshp[1])))
            d["self_imshp_logical_r"] = self.imshp_logical[1] #N.B. 1  not 0
            d["self_imshp_logical_c"] = self.imshp_logical[2]#N.B. 2  not 1
            d["self_imshp_logical_stride_r"] = int(N.ceil(self.imshp_logical[1] / float(self.imshp[1])))
            d["self_imshp_logical_stride_c"] = int(N.ceil(self.imshp_logical[2] / float(self.imshp[2])))
            if not self.imshp[0]==1: d["affectation"]="+="
            d["all_shape"]=1
            d["dim_zz_const"]="const"
        else:
            d["self_bsize"]="%(img2d)s->dimensions[0]"%d
            d["self_nkern"]="%(filtersflipped)s->dimensions[0]"%d
            d["self_outshp0"]="-1"
            d["self_outshp1"]="-1"
            d["self_imshp0"]="%(img2d)s->dimensions[1]"%d
            d["self_imshp1"]="%(img2d)s->dimensions[2]"%d
            d["self_imshp2"]="%(img2d)s->dimensions[3]"%d
            d["self_kshp0"]="%(filtersflipped)s->dimensions[2]"%d
            d["self_kshp1"]="%(filtersflipped)s->dimensions[3]"%d
            d["affectation"]="+="
            d["all_shape"]=0
            d["dim_zz_const"]=""

        if self.kshp_logical_top_aligned:
            d["self_kshp_logical_offset_r"] = 0
            d["self_kshp_logical_offset_c"] = 0
        elif self.imshp != self.imshp_logical or self.kshp != self.kshp_logical:
            rstride = d["self_kshp_logical_stride_r"]
            cstride = d["self_kshp_logical_stride_c"]
            d["self_kshp_logical_offset_r"] = (self.kshp_logical[0] - (self.kshp[0]*rstride) - 1+rstride) % rstride
            d["self_kshp_logical_offset_c"] = (self.kshp_logical[1] - (self.kshp[1]*cstride) - 1+cstride) % cstride
            del rstride, cstride
        
        if node.inputs[0].type.dtype=="float32": d["type"]="float"
        elif node.inputs[0].type.dtype=="float64": d["type"]="double"
        else: raise Exception("Type %s not implemented"%node.inputs[0].type.dtype)
        d["gemm"]='dgemm_'
        if not d["type"]=="double":d["gemm"]='sgemm_'

        if self.imshp != self.imshp_logical or self.kshp != self.kshp_logical:
            if self.verbose:
                print "return imshp!=imshp_logical or self.kshp != self.kshp_logical shape version"
            return _conv_op_code_a % d

        if self.unroll_patch:
            if self.verbose:
                print "return unroll patch version",self.dx,self.dy
            return _conv_op_code_unroll_patch%d
        if self.unroll_batch>0 or self.unroll_kern>0:
            if self.unroll_batch<=0: self.unroll_batch=1
            if self.unroll_kern<=0: self.unroll_kern=1
            if self.verbose:
                print "return unrolled batch and kern code by",self.unroll_batch, self.unroll_kern
            return gen_conv_code_unroll_batch_kern(d, self.unroll_batch,
                                                   self.unroll_kern)

        #TODO: should we choose the unroll size automatically with the bigger divisor under 5? 
        if self.out_mode == 'valid' and self.dx==0 and self.dy==0:
            if self.verbose:
                print "return gemm version"
            return _conv_op_code_valid_gemm % d
        else:
            if self.verbose:
                print "return no gemm version"
            return _conv_op_code_a % d

def convolve2(kerns, kshp, nkern, images, imshp, bsize, step=(1,1),
              bias=None, mode='valid', **d):
    """
    param kerns: kernel tensor
    param kshp:  tuple(kern row, kern wid)
    param nkern: int the number of kernel
    param images:image tensor
    param imshp: tuple([stack size,] image row, image wid)
    param bsize: batch size
    param step:  subsampling to apply to the output tuple(row, wid)
    param bias:  if True, will add a bias
    param mode:  'valid' or 'full'
    return:      tuple(theano graph with the output of ConvOp flattened to 2 dimensions, ?)
    """
    #TODO: remove the bias argument from this function because convolution has nothing to do with a bias

    # if imshp, is a tuple, images contains one input dimension
    if len(imshp)!=3:
        nvis_dim = 1
    else: nvis_dim = imshp[0]

    # all these reshapes should happen in place
    imrshp   = tensor.as_tensor([bsize] + list(imshp))
    imtensor = tensor.reshape(images, imrshp)

    kernrshp   = tensor.as_tensor([nkern, nvis_dim] + list(kshp))
    kerntensor = tensor.reshape(kerns, kernrshp)
 
    convop = ConvOp(imshp, kshp, nkern, bsize, step[0], step[1],
                    output_mode=mode, **d)
    convout = convop(imtensor, kerntensor)
   
    if bias:
        biastensor = tensor.DimShuffle((False,), ('x',0,'x','x'), inplace=True)(bias)
        convout = convout + biastensor
        
    rval = tensor.flatten(convout, 2)
    return rval, N.hstack((nkern, convop.outshp))

_conv_op_code_a = """
const int mode=%(mode)s;
int typenum=0, typenum_f=0;
PyArrayObject *ain1=NULL, *ain2=NULL, *filtersflipped_arr=NULL, *img2d_arr=NULL;
const %(type)s fill_value = 0;

int type_im=PyArray_TYPE(%(img2d)s);
int type_ker=PyArray_TYPE(%(filtersflipped)s);

npy_intp dim_zz[2]={%(self_outshp0)s,%(self_outshp1)s};
npy_intp dim_im_phys[2]={%(self_imshp1)s,%(self_imshp2)s};
npy_intp dim_im_log[2]={%(self_imshp_logical_r)s,%(self_imshp_logical_c)s};
npy_intp dim_ker_phys[2]={%(self_kshp0)s,%(self_kshp1)s};
npy_intp dim_ker_log[2]={%(self_kshp_logical_r)s,%(self_kshp_logical_c)s};

PyArray_Dims img2d_shape;
npy_intp img2d_dim[4]={1,1,0,0};
img2d_shape.ptr=img2d_dim;
img2d_shape.len=4;

PyArray_Dims kerns_shape;
npy_intp kerns_dim[4]={1,1,0,0};
kerns_shape.ptr=kerns_dim;
kerns_shape.len=4;
PyObject *img2d=NULL, *contig, *filtersflipped=NULL;


if(%(img2d)s->nd==2){
  img2d_dim[3]=%(img2d)s->dimensions[1];
  img2d_dim[2]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==3){
  img2d_dim[3]=%(img2d)s->dimensions[2];
  img2d_dim[2]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==4){
  img2d_dim[3]=%(img2d)s->dimensions[3];
  img2d_dim[2]=%(img2d)s->dimensions[2];
  img2d_dim[1]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else {
    PyErr_SetString(PyExc_ValueError, "img don't have a good shape");
    %(fail)s;
}

if(%(filtersflipped)s->nd==3){
  kerns_dim[3]=%(filtersflipped)s->dimensions[2];
  kerns_dim[2]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else if(%(filtersflipped)s->nd==4){
  kerns_dim[3]=%(filtersflipped)s->dimensions[3];
  kerns_dim[2]=%(filtersflipped)s->dimensions[2];
  kerns_dim[1]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else{
    std:stringstream temp;
    temp << "nddim="<<%(filtersflipped)s->nd;
    std::string param = temp.str();
    PyErr_SetString(PyExc_ValueError,
      ("kernel don't have a good shape. " + param).c_str());
    %(fail)s;
}

img2d = PyArray_Newshape(%(img2d)s,&img2d_shape, PyArray_CORDER);
img2d_arr = (PyArrayObject*)img2d;
if ((img2d_arr->strides[3] != (npy_intp)sizeof(%(type)s))
     || (img2d_arr->strides[2] != img2d_arr->dimensions[3]*(npy_intp)sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)img2d));
    Py_DECREF(img2d);
    img2d = contig;
    if (!PyArray_ISCONTIGUOUS(img2d)){
        PyErr_SetString(PyExc_ValueError, "img2d isn't contiguous");
        %(fail)s;
    }
}
img2d_arr = (PyArrayObject*)img2d;

filtersflipped = PyArray_Newshape(%(filtersflipped)s,&kerns_shape, PyArray_CORDER);
filtersflipped_arr = (PyArrayObject*)filtersflipped;
if ((filtersflipped_arr->strides[3] != (npy_intp)sizeof(%(type)s)) 
     || (filtersflipped_arr->strides[2] != filtersflipped_arr->dimensions[3]*(npy_intp)sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)filtersflipped));
    Py_DECREF(filtersflipped);
    filtersflipped = contig;
    if (!PyArray_ISCONTIGUOUS(filtersflipped)){
        PyErr_SetString(PyExc_ValueError, "filtersflipped isn't contiguous");
        %(fail)s;
    }
}
filtersflipped_arr = (PyArrayObject*)filtersflipped;

if(mode != VALID && mode != FULL){
  PyErr_SetString(PyExc_ValueError, "invalid mode, only full and valid are supported"); %(fail)s;
}
typenum = PyArray_ObjectType((PyObject*)%(img2d)s, 0);
typenum_f = PyArray_ObjectType((PyObject*)%(filtersflipped)s, 0);
if (typenum < 0) {PyErr_SetString(PyExc_ValueError, "Invalid type"); %(fail)s;}
if (typenum != typenum_f) {PyErr_SetString(PyExc_ValueError, "Input types must match"); %(fail)s;}

if (!img2d) %(fail)s;
if (!filtersflipped) %(fail)s;
if ((!%(z)s)
  || *PyArray_DIMS(%(z)s)!=4
  ||(%(z)s->dimensions[0] != %(self_bsize)s)
  ||(%(z)s->dimensions[1] != %(self_nkern)s)
  ||(%(z)s->dimensions[2] != dim_zz[0])
  || (%(z)s->dimensions[3] != dim_zz[1])
  )
{
  {Py_XDECREF(%(z)s);}
  npy_intp dims[4] = {0,0,0,0};
  dims[0]=%(self_bsize)s;
  dims[1]=%(self_nkern)s;
  dims[2]=dim_zz[0];
  dims[3]=dim_zz[1];
  %(z)s = (PyArrayObject*) PyArray_ZEROS(4, dims, typenum,0);
}else{
  //PyArray_FILLWBYTE((PyObject*)%(z)s,0);
}

int Os[2];
Os[0]=%(self_outshp0)s;
Os[1]=%(self_outshp1)s;

for(int b=0;b< %(self_bsize)s;b++){
  for(int n_kern=0;n_kern<%(self_nkern)s;n_kern++){

    //assertions
    if (%(z)s->strides[0] != %(z)s->dimensions[1] *%(z)s->dimensions[2] *%(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[1] != %(z)s->dimensions[2] * %(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[2] != %(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[3] != (npy_intp)sizeof(%(type)s)) %(fail)s;

    %(type)s * __restrict__ out=(%(type)s *)(PyArray_GETPTR2(%(z)s,b,n_kern));
    for (int i = 0; i < dim_zz[0]*dim_zz[1]; ++i) out[i] = 0;

    for(int stack_size=0;stack_size<%(self_imshp0)s;stack_size++){

      const %(type)s * __restrict__ in=(%(type)s *)(PyArray_GETPTR2(img2d,b,stack_size));
      const %(type)s * __restrict__ hvals=(%(type)s *)(PyArray_GETPTR2(filtersflipped,n_kern,stack_size));


      for (int iter_m=0; iter_m < Os[0]; iter_m++) {
                                               /// Reposition index into input image based on requested output size
        int pos_m = iter_m*%(self_dx)s;        //row position in logical output image
        int new_m;                             //row anchor in logical input image (we will loop upward from here)
        if (mode == FULL) new_m = pos_m ;
        else new_m = (pos_m+dim_ker_log[0]-1);

        for (int iter_n=0; iter_n < Os[1]; iter_n++) {  // loop over columns
          int pos_n=iter_n*%(self_dy)s;        // current col position in logical output image
          %(type)s sum=0;

          // Sum over kernel, if index into image is out of bounds
          // fill with the value
          for (int j_log=0; j_log < %(self_kshp_logical_r)s; j_log++) { // loop over logical rows in kernel

            int ind0_log = (new_m-j_log);                                   // ind0_log: row position in logical input image

            if ((j_log < %(self_kshp_logical_offset_r)s) || (j_log - %(self_kshp_logical_offset_r)s) MOD %(self_kshp_logical_stride_r)s)
                continue;

            if (ind0_log MOD %(self_imshp_logical_stride_r)s)
                continue;

            int j_phys = ((j_log- %(self_kshp_logical_offset_r)s) / %(self_kshp_logical_stride_r)s);
            int ind0_phys = (ind0_log / %(self_imshp_logical_stride_r)s);
            //std::cerr <<"j_log" << j_log << " j_phys " << j_phys << " " << ind0_phys << "\\n";

            if(mode==FULL){
              const %(type)s * idx_hvals=&hvals[j_phys*dim_ker_phys[1]]; //This is a pointer to the current row of the kernel
              if(ind0_log < 0 || ind0_log >= dim_im_log[0]){
                   // the current row of the kernel is off the image
              }else{
                int k = max((int)(pos_n-dim_im_log[1])+1,0);
                int max_k=min(pos_n+1,(int)dim_ker_log[1]);
                const %(type)s * idx_in=&in[ind0_phys*dim_im_phys[1]];
                for (int ind1_log=pos_n-k; k<max_k; k++,ind1_log--) {
                    if (1)
                    {
                                if ((k < %(self_kshp_logical_offset_c)s) || (k - %(self_kshp_logical_offset_c)s) MOD %(self_kshp_logical_stride_c)s)
                                    continue;

                                if (ind1_log MOD %(self_imshp_logical_stride_c)s)
                                    continue;
                    }
                  sum+= idx_hvals[(k-%(self_kshp_logical_offset_c)s) / %(self_kshp_logical_stride_c)s] * idx_in[ind1_log / %(self_imshp_logical_stride_c)s];
                }
              }
            }else{
              const %(type)s* idx_in=&in[ind0_phys*dim_im_phys[1]]; //JB: should be dim_im[1] right? (was dim_im[0])
              const %(type)s* idx_hvals=&hvals[j_phys*dim_ker_phys[1]];
              int new_n = (pos_n+dim_ker_log[1]-1);
              if (%(self_imshp_logical_stride_c)s != 1)  // a general loop
              {
                  for (int k=0,last=new_n; k < dim_ker_log[1]; k++,last--) {
                        if ((k < %(self_kshp_logical_offset_c)s) || (k - %(self_kshp_logical_offset_c)s) MOD %(self_kshp_logical_stride_c)s)
                            continue;

                        else if (last MOD %(self_imshp_logical_stride_c)s)
                            continue;
                            else
                            {
                    sum+=idx_hvals[(k-%(self_kshp_logical_offset_c)s) / %(self_kshp_logical_stride_c)s]*idx_in[last/%(self_imshp_logical_stride_c)s];
                    }
                  }
              }
              else  // self_imshp_stride_c == 1
              {
                  int offset = %(self_kshp_logical_offset_c)s;
                  int k_phys=0;
                  for (int k_log=offset,last=new_n-offset; k_log < dim_ker_log[1]; ) {
                    sum += idx_hvals[k_phys]*idx_in[last];
                    ++k_phys;
                    last -= %(self_kshp_logical_stride_c)s;
                    k_log += %(self_kshp_logical_stride_c)s;
                  }
              }
            }
          }//for j
          out[iter_m*dim_zz[1]+iter_n] %(affectation)s sum;
        }//for n
      }//for m
    }//for stack_size
    if (0 && (mode==FULL)){
      for (int i = 0; i < dim_zz[0]*dim_zz[1]; ++i) 
        std::cout << " " << out[i];
      std::cout << "\\n";
    }
  }//for n_kern
}//for b
Py_XDECREF(img2d);
Py_XDECREF(filtersflipped);
"""


#########  
#########  ConvOp c_code for valid mode (uses gemm)
#########

_conv_op_code_valid_gemm = """
int typenum=0, typenum_f=0;
PyArrayObject *ain1=NULL, *ain2=NULL, *img2d_arr=NULL;
const int NKERN = %(self_nkern)s;

int type_im=PyArray_TYPE(%(img2d)s);
int type_ker=PyArray_TYPE(%(filtersflipped)s);

npy_intp dim_zz[2]={%(self_outshp0)s,%(self_outshp1)s};
npy_intp dim_im[2]={%(self_imshp1)s,%(self_imshp2)s};
npy_intp dim_ker[2]={%(self_kshp0)s,%(self_kshp1)s};

PyArray_Dims img2d_shape;
npy_intp img2d_dim[4]={1,1,0,0};
img2d_shape.ptr=img2d_dim;
img2d_shape.len=4;

PyArray_Dims kerns_shape;
npy_intp kerns_dim[4]={1,1,0,0};
kerns_shape.ptr=kerns_dim;
kerns_shape.len=4;
PyObject *img2d=NULL, *contig;

if(%(img2d)s->nd==2){
  img2d_dim[3]=%(img2d)s->dimensions[1];
  img2d_dim[2]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==3){
  img2d_dim[3]=%(img2d)s->dimensions[2];
  img2d_dim[2]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==4){
  img2d_dim[3]=%(img2d)s->dimensions[3];
  img2d_dim[2]=%(img2d)s->dimensions[2];
  img2d_dim[1]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else {
    PyErr_SetString(PyExc_ValueError, "img don't have a good shape");
    %(fail)s;
}

if(%(filtersflipped)s->nd==3){
  kerns_dim[3]=%(filtersflipped)s->dimensions[2];
  kerns_dim[2]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else if(%(filtersflipped)s->nd==4){
  kerns_dim[3]=%(filtersflipped)s->dimensions[3];
  kerns_dim[2]=%(filtersflipped)s->dimensions[2];
  kerns_dim[1]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else{
    std:stringstream temp;
    temp << "nddim="<<%(filtersflipped)s->nd;
    std::string param = temp.str();
    PyErr_SetString(PyExc_ValueError,
      ("kernel don't have a good shape. " + param).c_str());
    %(fail)s;
}
if (NKERN != kerns_dim[0])
{
    PyErr_SetString(PyExc_NotImplementedError, "nonsense nkern");
    %(fail)s;
}

img2d = PyArray_Newshape(%(img2d)s,&img2d_shape, PyArray_CORDER);
img2d_arr = (PyArrayObject*)img2d;
if ((img2d_arr->strides[3] != (npy_intp)sizeof(%(type)s)) 
     || (img2d_arr->strides[2] != img2d_arr->dimensions[3]*(npy_intp)sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)img2d));
    Py_DECREF(img2d);
    img2d = contig;
    if (!PyArray_ISCONTIGUOUS(img2d)){
        PyErr_SetString(PyExc_ValueError, "img2d isn't contiguous");
        %(fail)s;
    }
}
img2d_arr = (PyArrayObject*)img2d;

typenum = PyArray_ObjectType((PyObject*)%(img2d)s, 0);
typenum_f = PyArray_ObjectType((PyObject*)%(filtersflipped)s, 0);
if (typenum < 0) {PyErr_SetString(PyExc_ValueError, "Invalid type"); %(fail)s;}
if (typenum != typenum_f) {PyErr_SetString(PyExc_ValueError, "Input types must match"); %(fail)s;}

if (!img2d) {
    PyErr_SetString(PyExc_ValueError, "Null argument img2d");
    %(fail)s;
}
if ((!%(z)s)
  || *PyArray_DIMS(%(z)s)!=4
  ||(%(z)s->dimensions[0] != %(self_bsize)s)
  ||(%(z)s->dimensions[1] != %(self_nkern)s)
  ||(%(z)s->dimensions[2] != dim_zz[0])
  || (%(z)s->dimensions[3] != dim_zz[1])
  )
{
  {Py_XDECREF(%(z)s);}
  npy_intp dims[4] = {0,0,0,0};
  dims[0]=%(self_bsize)s;
  dims[1]=%(self_nkern)s;
  dims[2]=dim_zz[0];
  dims[3]=dim_zz[1];
  %(z)s = (PyArrayObject*) PyArray_ZEROS(4, dims, typenum,0);
}else{
  PyArray_FILLWBYTE((PyObject*)%(z)s,0);
}

int Os[2];
Os[0] = dim_im[0]-dim_ker[0]+1;
Os[1] = dim_im[1]-dim_ker[1]+1;

// allocate a temporary buffer for storing the inner product of each nth kernel row 
// with each row of an image
{
%(type)s * kbuf = (%(type)s *)malloc((Os[0] * NKERN + PyArray_Size((PyObject*)%(filtersflipped)s))* (npy_intp)sizeof(%(type)s));
int kbufstride = NKERN;
%(type)s * myfilters = kbuf + Os[0] * NKERN;

//copy out filtersflipped into filters un-flipped format
//std::cerr << "__filling myfilters__\\n";
for(int i=0;i < kerns_dim[0];++i){
    for(int j=0;j < kerns_dim[1];++j){
        for(int k=0;k < kerns_dim[2];++k){
            for(int l=0;l < kerns_dim[3];++l){
                %(type)s * ff = ((%(filtersflipped)s)->nd == 3)
                    ? (%(type)s *)PyArray_GETPTR3(%(filtersflipped)s, i, kerns_dim[2]-1-k, kerns_dim[3]-1-l)
                    : (%(type)s *)PyArray_GETPTR4(%(filtersflipped)s, i, j, kerns_dim[2]-1-k, kerns_dim[3]-1-l);
                myfilters[i * (kerns_dim[1]*kerns_dim[2]*kerns_dim[3]) 
                          + j * (kerns_dim[2]*kerns_dim[3])
                          + k * (kerns_dim[3])
                          + l] = ff[0];
                //std::cerr << " " << ff[0];
            }
            //std::cerr << "\\n";
        }
        //std::cerr << "(end of stack/batch " <<j << "/" << i << "  ) \\n";
    }
}

//std::cerr << "-----new loop ----\\n";
for(int b=0;b< %(self_bsize)s;b++){
    for (int img_col = 0; img_col < Os[1]; ++img_col){
        for (int filter_row = 0; filter_row < kerns_dim[2]; ++filter_row){
            for (int stackidx = 0; stackidx < %(self_imshp0)s; ++stackidx){
                %(type)s * img_colview = 
                    (%(type)s *)(PyArray_GETPTR4(img2d, b, stackidx, filter_row, img_col));
                %(type)s * filter_rows = myfilters + stackidx * (kerns_dim[2]*kerns_dim[3]) +
                filter_row * kerns_dim[3];
                //std::cerr << "filterview offset: " << filter_rows - myfilters << "\\n";

                char N = 'N'; char T = 'T';
                int Nz0 = Os[0]; 
                int Nz1 = NKERN;
                int K = kerns_dim[3];
                %(type)s alpha = 1.0;
                %(type)s beta = stackidx ? 1.0 : 0.0;
                int imgview_stride = dim_im[1];
                int filter_rows_stride =kerns_dim[1]*kerns_dim[2]*kerns_dim[3];
                //remember, Fortran wants a column-major interpretation
                assert(img2d->strides[3] == (npy_intp)sizeof(%(type)s));

                if (0){
                    std::cerr << "b " << b << " img_col " << img_col << " filterrow " << filter_row << " stackidx " <<stackidx << "\\n";
                    std::cerr << "colview (physical layout) stride: " << imgview_stride << "\\n";
                    for (int ii = 0; ii < Nz0; ++ii){
                        for (int jj = 0; jj < K; ++jj){
                            std::cerr << " " << img_colview[ii * imgview_stride + jj];
                        }
                        std::cerr << "\\n";
                    }
                    std::cerr << "filterview ("<<filter_row<<"'th rows) stride: " << filter_rows_stride << "\\n";
                    for (int ii = 0; ii < Nz1; ++ii){
                        for (int jj = 0; jj < K; ++jj){
                            std::cerr << " " << filter_rows[ii * filter_rows_stride + jj];
                        }
                        std::cerr << "\\n";
                    }

                    std::cerr << Nz1 << " " << Nz0 << " " << K << "\\n" ;
                }

                %(gemm)s(&T, &N, 
                    &Nz1, &Nz0, &K,
                    &alpha, 
                    filter_rows, &filter_rows_stride,
                    img_colview, &imgview_stride, 
                    &beta, kbuf, &kbufstride);

                if (0){
                    std::cerr << "z (logical layout) beta" << beta << "\\n";
                    for (int ii = 0; ii < Nz0; ++ii){
                        for (int jj = 0; jj < Nz1; ++jj){
                            std::cerr << " " << kbuf[ii * kbufstride + jj];
                        }
                        std::cerr << "\\n";
                    }
                }
            }
            // now kbuf the sum over the stack, put it into the outbuf
            for (int img_row = 0; img_row < Os[0]; ++img_row) {
                for (int kernel_idx = 0; kernel_idx < NKERN; ++kernel_idx) {
                    %(type)s * z_p =  (%(type)s *)PyArray_GETPTR4(%(z)s, b, kernel_idx, img_row, img_col);
                    if (0)
                    {
                        if (b >= %(z)s->dimensions[0]) %(fail)s;
                        if (kernel_idx >= %(z)s->dimensions[1]) %(fail)s;
                        if (img_row >= %(z)s->dimensions[2]) %(fail)s;
                        if (img_col >= %(z)s->dimensions[3]) %(fail)s;
                    }
                    z_p[0] += kbuf[img_row * kbufstride + kernel_idx];
                }
            }
        }
    }
}
free(kbuf);
}
Py_XDECREF(img2d);
"""

def gen_conv_code_unroll_batch_kern(d,unroll_bsize=1, unroll_ksize=1):
    """ c_code for ConvOp that unroll the batch size loop
    """
    assert unroll_bsize>0 and unroll_ksize>0
    if d.has_key("unroll_bsize") or d.has_key("unroll_ksize") or d.has_key("unroll_iter") or d.has_key("unroll_biter") or d.has_key("unroll_kiter"):
        raise Exception("We can't use this dictionnary as we will overwrite some of its containt")
    d=d.copy()
        
    d["unroll_bsize"]=unroll_bsize
    d["unroll_ksize"]=unroll_ksize
    def my_dup(st,size):
        s=""
        for i in range(size):
            d["unroll_iter"]=i
            s+=st%d
        return s+"\n"
    def my_dup2(st):
        s=""
        iter=0
        for i in range(unroll_bsize):
            d["unroll_biter"]=i
            for j in range(unroll_ksize):
                d["unroll_kiter"]=j
                d["unroll_iter"]=iter
                iter+=1
                s+=st%d
        return s+"\n"
    ret = """
const int mode=%(mode)s;
int typenum=0, typenum_f=0;
PyArrayObject *ain1=NULL, *ain2=NULL, *filtersflipped_arr=NULL, *img2d_arr=NULL;
const %(type)s fill_value = 0;

int type_im=PyArray_TYPE(%(img2d)s);
int type_ker=PyArray_TYPE(%(filtersflipped)s);

npy_intp dim_zz[2]={%(self_outshp0)s,%(self_outshp1)s};
npy_intp dim_im[2]={%(self_imshp1)s,%(self_imshp2)s};
npy_intp dim_ker[2]={%(self_kshp0)s,%(self_kshp1)s};

PyArray_Dims img2d_shape;
npy_intp img2d_dim[4]={1,1,0,0};
img2d_shape.ptr=img2d_dim;
img2d_shape.len=4;

PyArray_Dims kerns_shape;
npy_intp kerns_dim[4]={1,1,0,0};
kerns_shape.ptr=kerns_dim;
kerns_shape.len=4;
PyObject *img2d=NULL, *contig, *filtersflipped=NULL;

if(%(img2d)s->nd==2){
  img2d_dim[3]=%(img2d)s->dimensions[1];
  img2d_dim[2]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==3){
  img2d_dim[3]=%(img2d)s->dimensions[2];
  img2d_dim[2]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==4){
  img2d_dim[3]=%(img2d)s->dimensions[3];
  img2d_dim[2]=%(img2d)s->dimensions[2];
  img2d_dim[1]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else {
    std:stringstream temp;
    temp << "nddim="<<%(img2d)s->nd;
    std::string param = temp.str();
    PyErr_SetString(PyExc_ValueError,
      ("img don't have a good shape. " + param).c_str());
    %(fail)s;
}

if(%(filtersflipped)s->nd==3){
  kerns_dim[3]=%(filtersflipped)s->dimensions[2];
  kerns_dim[2]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else if(%(filtersflipped)s->nd==4){
  kerns_dim[3]=%(filtersflipped)s->dimensions[3];
  kerns_dim[2]=%(filtersflipped)s->dimensions[2];
  kerns_dim[1]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else{
    PyErr_SetString(PyExc_ValueError, "kernel don't have a good shape");
    %(fail)s;
}

img2d = PyArray_Newshape(%(img2d)s,&img2d_shape, PyArray_CORDER);
img2d_arr = (PyArrayObject*)img2d;
if ((img2d_arr->strides[3] != (npy_intp)sizeof(%(type)s)) 
     || (img2d_arr->strides[2] != img2d_arr->dimensions[3]*(npy_intp)sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)img2d));
    Py_DECREF(img2d);
    img2d = contig;
    if (!PyArray_ISCONTIGUOUS(img2d)){
        PyErr_SetString(PyExc_ValueError, "img2d isn't contiguous");
        %(fail)s;
    }
}
img2d_arr = (PyArrayObject*)img2d;

filtersflipped = PyArray_Newshape(%(filtersflipped)s,&kerns_shape, PyArray_CORDER);
filtersflipped_arr = (PyArrayObject*)filtersflipped;
if ((filtersflipped_arr->strides[3] != (npy_intp)sizeof(%(type)s)) 
     || (filtersflipped_arr->strides[2] != filtersflipped_arr->dimensions[3]*(npy_intp)sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)filtersflipped));
    Py_DECREF(filtersflipped);
    filtersflipped = contig;
    if (!PyArray_ISCONTIGUOUS(filtersflipped)){
        PyErr_SetString(PyExc_ValueError, "filtersflipped isn't contiguous");
        %(fail)s;
    }
}
filtersflipped_arr = (PyArrayObject*)filtersflipped;

if(mode != VALID && mode != FULL){
  PyErr_SetString(PyExc_ValueError, "invalid mode, only full and valid are supported"); %(fail)s;
}
typenum = PyArray_ObjectType((PyObject*)%(img2d)s, 0);
typenum_f = PyArray_ObjectType((PyObject*)%(filtersflipped)s, 0);
if (typenum < 0) {PyErr_SetString(PyExc_ValueError, "Invalid type"); %(fail)s;}
if (typenum != typenum_f) {PyErr_SetString(PyExc_ValueError, "Input types must match"); %(fail)s;}

if (!img2d) %(fail)s;
if (!filtersflipped) %(fail)s;
if ((!%(z)s)
  || *PyArray_DIMS(%(z)s)!=4
  ||(%(z)s->dimensions[0] != %(self_bsize)s)
  ||(%(z)s->dimensions[1] != %(self_nkern)s)
  ||(%(z)s->dimensions[2] != dim_zz[0])
  || (%(z)s->dimensions[3] != dim_zz[1])
  )
{
  {Py_XDECREF(%(z)s);}
  npy_intp dims[4] = {0,0,0,0};
  dims[0]=%(self_bsize)s;
  dims[1]=%(self_nkern)s;
  dims[2]=dim_zz[0];
  dims[3]=dim_zz[1];
  %(z)s = (PyArrayObject*) PyArray_ZEROS(4, dims, typenum,0);
}else{
  //PyArray_FILLWBYTE((PyObject*)%(z)s,0);
}

int Os[2];
Os[0]=%(self_outshp0)s;
Os[1]=%(self_outshp1)s;

for(int b=0;b< %(self_bsize)s ;b+=%(unroll_bsize)s){
  for(int n_kern=0;n_kern<%(self_nkern)s;n_kern+=%(unroll_ksize)s){

    //assertions
    if (%(z)s->strides[0] != %(z)s->dimensions[1] *%(z)s->dimensions[2] *%(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[1] != %(z)s->dimensions[2] * %(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[2] != %(z)s->dimensions[3] * (npy_intp)sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[3] != (npy_intp)sizeof(%(type)s)) %(fail)s;
"""%d
    ret+=my_dup2("%(type)s * __restrict__ out%(unroll_iter)s=(%(type)s *)(PyArray_GETPTR2(%(z)s,b+%(unroll_biter)s,n_kern+%(unroll_kiter)s));")
    ret+=my_dup("for (int i = 0; i < dim_zz[0]*dim_zz[1]; ++i) out%(unroll_iter)s[i] = 0;",unroll_bsize*unroll_ksize)
    ret+="""
    for(int stack_size=0;stack_size<%(self_imshp0)s;stack_size++){
"""%d
    ret+=my_dup("const %(type)s * __restrict__ in%(unroll_iter)d=(%(type)s *)(PyArray_GETPTR2(img2d,b+%(unroll_iter)s,stack_size));", unroll_bsize)
    ret+=my_dup("const %(type)s * __restrict__ hvals%(unroll_iter)s=(%(type)s *)(PyArray_GETPTR2(filtersflipped,n_kern+%(unroll_iter)s,stack_size));",unroll_ksize)
    ret+="""

      int new_m;

      for (int iter_m=0; iter_m < Os[0]; iter_m++) {
        // Reposition index into input image based on requested output size
        int pos_m = iter_m*%(self_dx)s;//The position of the patch in the image
        if (mode == FULL) new_m = pos_m ;
        else new_m = (pos_m+dim_ker[0]-1);

        for (int iter_n=0; iter_n < Os[1]; iter_n++) {  // loop over columns 
          int pos_n=iter_n*%(self_dy)s;
        """%d
    ret+=my_dup("%(type)s sum%(unroll_iter)s=0;", unroll_bsize*unroll_ksize)
    ret+="""

          // Sum over kernel, if index into image is out of bounds
          // fill with the value
          for (int j=0; j < dim_ker[0]; j++) {
            int ind0 = (new_m-j);

            if(mode==FULL){
"""%d
    ret+=my_dup("const %(type)s * idx_hvals%(unroll_iter)s=&hvals%(unroll_iter)s[j*dim_ker[1]];",unroll_ksize)
    ret+="""
              if(ind0 < 0 || ind0 >= dim_im[0]){
                if(fill_value!=0)
                  for (int k=0; k < dim_ker[1]; k++) {
"""%d
    ret+=my_dup2("sum%(unroll_iter)s += idx_hvals%(unroll_kiter)s[k] * fill_value;")
    ret+="""
                  }
              }else{
                //do the part where kernel is to the right of the img

                int k=0,max_k=max((int)(pos_n-dim_im[1])+1,0);
                if(fill_value!=0){ 
                
                  for(k=0;k<max_k;k++){
"""%d
    ret+=my_dup2("sum%(unroll_iter)s += idx_hvals%(unroll_kiter)s[k] * fill_value;")
    ret+="""
                  }
                }else {k=max_k;}
                
                //do the part where the kernel is on the img
                max_k=min(pos_n+1,(int)dim_ker[1]);
"""%d
    ret+=my_dup("const %(type)s * idx_in%(unroll_iter)s=&in%(unroll_iter)s[ind0*dim_im[1]];", unroll_bsize)
    ret+="""
                for (int ind1=pos_n-k; k<max_k; k++,ind1--) {

"""%d
    ret+=my_dup2("sum%(unroll_iter)s+= idx_hvals%(unroll_kiter)s[k] * idx_in%(unroll_biter)s[ind1];")
    ret+="""
                }
                //do the part to the left of the img
                if(fill_value!=0)
                  for(;k<dim_ker[1];k++){
"""%d
    ret+=my_dup2("sum%(unroll_iter)s += idx_hvals%(unroll_kiter)s[k] * fill_value;")
    ret+="""
                  }
              }
            }else{//valid mode
"""%d
    ret+=my_dup("const %(type)s* idx_in%(unroll_iter)s=&in%(unroll_iter)s[ind0*dim_im[1]];", unroll_bsize)
    ret+=my_dup("const %(type)s* idx_hvals%(unroll_iter)s=&hvals%(unroll_iter)s[j*dim_ker[1]];",unroll_ksize)
    ret+="""
              int new_n = (pos_n+dim_ker[1]-1);

              for (int k=0,last=new_n; k < dim_ker[1]; k++,last--) {
"""%d
    ret+=my_dup2("sum%(unroll_iter)s+=idx_hvals%(unroll_kiter)s[k]*idx_in%(unroll_biter)s[last];")
    ret+="""
              }
            }

          }//for j
"""%d
    ret+=my_dup("out%(unroll_iter)s[iter_m*dim_zz[1]+iter_n] %(affectation)s sum%(unroll_iter)s;", unroll_bsize*unroll_ksize)
    ret+="""
        }//for n
      }//for m
    }//for stack_size
  }//for n_kern
}//for b
Py_XDECREF(img2d);
Py_XDECREF(filtersflipped);
"""
    return ret

_conv_op_code_unroll_patch = """
const int mode=%(mode)s;
int typenum=0, typenum_f=0;
PyArrayObject *ain1=NULL, *ain2=NULL, *filtersflipped_arr=NULL, *img2d_arr=NULL;
const %(type)s fill_value = 0;//only value of 0 are currently tested and correctly implemented

int type_im=PyArray_TYPE(%(img2d)s);
int type_ker=PyArray_TYPE(%(filtersflipped)s);

const npy_intp dim_im[2]={%(self_imshp1)s,%(self_imshp2)s};
const npy_intp dim_ker[2]={%(self_kshp0)s,%(self_kshp1)s};
%(dim_zz_const)s npy_intp dim_zz[2]={%(self_outshp0)s,%(self_outshp1)s};
#if !%(all_shape)s
  if (mode == FULL) {
    dim_zz[0] = (int)ceil((dim_im[0]+dim_ker[0]-1)/float(%(self_dx)s));
    dim_zz[1] = (int)ceil((dim_im[1]+dim_ker[1]-1)/float(%(self_dy)s));
  } else {
    dim_zz[0] = (int)ceil((dim_im[0]-dim_ker[0]+1)/float(%(self_dx)s));
    dim_zz[1] = (int)ceil((dim_im[1]-dim_ker[1]+1)/float(%(self_dy)s));
  }
#endif
PyArray_Dims img2d_shape;
npy_intp img2d_dim[4]={1,1,0,0};
img2d_shape.ptr=img2d_dim;
img2d_shape.len=4;

PyArray_Dims kerns_shape;
npy_intp kerns_dim[4]={1,1,0,0};
kerns_shape.ptr=kerns_dim;
kerns_shape.len=4;
PyObject *img2d=NULL, *contig, *filtersflipped=NULL;

if(%(img2d)s->nd==2){
  img2d_dim[3]=%(img2d)s->dimensions[1];
  img2d_dim[2]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==3){
  img2d_dim[3]=%(img2d)s->dimensions[2];
  img2d_dim[2]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else if(%(img2d)s->nd==4){
  img2d_dim[3]=%(img2d)s->dimensions[3];
  img2d_dim[2]=%(img2d)s->dimensions[2];
  img2d_dim[1]=%(img2d)s->dimensions[1];
  img2d_dim[0]=%(img2d)s->dimensions[0];
}else {
    PyErr_Format(PyExc_ValueError,
      "image don't have a good number of dimensions %%d. ", %(filtersflipped)s->nd);
    %(fail)s;
}

if(%(filtersflipped)s->nd==3){
  kerns_dim[3]=%(filtersflipped)s->dimensions[2];
  kerns_dim[2]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else if(%(filtersflipped)s->nd==4){
  kerns_dim[3]=%(filtersflipped)s->dimensions[3];
  kerns_dim[2]=%(filtersflipped)s->dimensions[2];
  kerns_dim[1]=%(filtersflipped)s->dimensions[1];
  kerns_dim[0]=%(filtersflipped)s->dimensions[0];
}else{
    PyErr_Format(PyExc_ValueError,
      "kernel don't have a good number of dimensions %%d. ", %(filtersflipped)s->nd);
    %(fail)s;
}

img2d = PyArray_Newshape(%(img2d)s,&img2d_shape, PyArray_CORDER);
img2d_arr = (PyArrayObject*)img2d;
if ((img2d_arr->strides[3] != sizeof(%(type)s)) 
     || (img2d_arr->strides[2] != img2d_arr->dimensions[3]*sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)img2d));
    Py_DECREF(img2d);
    img2d = contig;
    if (!PyArray_ISCONTIGUOUS(img2d)){
        PyErr_SetString(PyExc_ValueError, "img2d isn't contiguous");
        %(fail)s;
    }
}
img2d_arr = (PyArrayObject*)img2d;

filtersflipped = PyArray_Newshape(%(filtersflipped)s,&kerns_shape, PyArray_CORDER);
filtersflipped_arr = (PyArrayObject*)filtersflipped;
if ((filtersflipped_arr->strides[3] != sizeof(%(type)s)) 
     || (filtersflipped_arr->strides[2] != filtersflipped_arr->dimensions[3]*sizeof(%(type)s))){
    contig = (PyObject*)(PyArray_GETCONTIGUOUS((PyArrayObject*)filtersflipped));
    Py_DECREF(filtersflipped);
    filtersflipped = contig;
    if (!PyArray_ISCONTIGUOUS(filtersflipped)){
        PyErr_SetString(PyExc_ValueError, "filtersflipped isn't contiguous");
        %(fail)s;
    }
}
filtersflipped_arr = (PyArrayObject*)filtersflipped;

if(mode != VALID && mode != FULL){
  PyErr_SetString(PyExc_ValueError, "invalid mode, only full and valid are supported"); %(fail)s;
}

if(dim_zz[0]<=0 || dim_zz[1]<=0){
PyErr_Format(PyExc_ValueError,
      "Output dimensions are not valid %%dx%%d",dim_zz[0],dim_zz[1]);
      %(fail)s;
}

typenum = PyArray_ObjectType((PyObject*)%(img2d)s, 0);
typenum_f = PyArray_ObjectType((PyObject*)%(filtersflipped)s, 0);
if (typenum < 0) {PyErr_SetString(PyExc_ValueError, "Invalid type"); %(fail)s;}
if (typenum != typenum_f) {PyErr_SetString(PyExc_ValueError, "Input types must match"); %(fail)s;}

if (!img2d) %(fail)s;
if (!filtersflipped) %(fail)s;
if ((!%(z)s)
  || *PyArray_DIMS(%(z)s)!=4
  ||(%(z)s->dimensions[0] != %(self_bsize)s)
  ||(%(z)s->dimensions[1] != %(self_nkern)s)
  ||(%(z)s->dimensions[2] != dim_zz[0])
  || (%(z)s->dimensions[3] != dim_zz[1])
  )
{
  if (%(z)s) Py_DECREF(%(z)s);
  npy_intp dims[4] = {0,0,0,0};
  if(!dims) %(fail)s;
  dims[0]=%(self_bsize)s;
  dims[1]=%(self_nkern)s;
  dims[2]=dim_zz[0];
  dims[3]=dim_zz[1];
  %(z)s = (PyArrayObject*) PyArray_ZEROS(4, dims, typenum,0);
}else{
  //PyArray_FILLWBYTE((PyObject*)%(z)s,0);
}

for(int b=0;b< %(self_bsize)s;b++){
  for(int n_kern=0;n_kern<%(self_nkern)s;n_kern++){

    //assertions
    if (%(z)s->strides[0] != %(z)s->dimensions[1] *%(z)s->dimensions[2] *%(z)s->dimensions[3] * sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[1] != %(z)s->dimensions[2] * %(z)s->dimensions[3] * sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[2] != %(z)s->dimensions[3] * sizeof(%(type)s)) %(fail)s;
    if (%(z)s->strides[3] != sizeof(%(type)s)) %(fail)s;

    %(type)s * __restrict__ out=(%(type)s *)(PyArray_GETPTR2(%(z)s,b,n_kern));
    for (int i = 0; i < dim_zz[0]*dim_zz[1]; ++i) out[i] = 0;

    for(int stack_size=0;stack_size<%(self_imshp0)s;stack_size++){

      const %(type)s * __restrict__ in=(%(type)s *)(PyArray_GETPTR2(img2d,b,stack_size));
      const %(type)s * __restrict__ hvals=(%(type)s *)(PyArray_GETPTR2(filtersflipped,n_kern,stack_size));

      int new_m;

      for (int iter_m=0; iter_m < dim_zz[0]; iter_m++) {
        // Reposition index into input image based on requested output size
        int pos_m = iter_m*%(self_dx)s;//The position of the patch in the image
        if (mode == FULL) new_m = pos_m ;
        else new_m = (pos_m+dim_ker[0]-1);

        for (int iter_n=0; iter_n < dim_zz[1]; iter_n++) {  // loop over columns
          int pos_n=iter_n*%(self_dy)s;
          %(type)s sum=0;
          %(type)s sum2=0;
          %(type)s sum3=0;
          %(type)s sum4=0;
          int nb_sum=0;
          // Sum over kernel, if index into image is out of bounds
          // fill with the value
          for (int j=0; j < dim_ker[0]; j++) {
            int ind0 = (new_m-j);

            if(mode==FULL){
              const %(type)s * idx_hvals=&hvals[j*dim_ker[1]];
              if(ind0 < 0 || ind0 >= dim_im[0]){
                if(fill_value!=0)
                  for (int k=0; k < dim_ker[1]; k++) {
                    sum+= idx_hvals[k] * fill_value;
                  }
              }else{
                //do the part where kernel is to the right of the img
                int k=0,max_k=max((int)(pos_n-dim_im[1])+1,0);
                if(fill_value!=0){ 
                
                  for(k=0;k<max_k;k++){
                    sum+= idx_hvals[k]*fill_value;
                  }
                }else {k=max_k;}
                
                //do the part where the kernel is on the img
                max_k=min(pos_n+1,(int)dim_ker[1]);
                const %(type)s * idx_in=&in[ind0*dim_im[1]];

                if(iter_n + 4*%(self_dy)s < dim_zz[1]
                         && iter_n>dim_ker[1]-1+3 
                         && iter_n<dim_im[1]-dim_ker[1]+1-3){
                  nb_sum=4;
                  for (int ind1=pos_n-k; k<max_k; k++,ind1--) {
                    sum+=idx_hvals[k]*idx_in[ind1];
                    sum2+=idx_hvals[k]*idx_in[ind1+%(self_dy)s];
                    sum3+=idx_hvals[k]*idx_in[ind1+2*%(self_dy)s];
                    sum4+=idx_hvals[k]*idx_in[ind1+3*%(self_dy)s];
                  }
                }else if(iter_n + 2*%(self_dy)s < dim_zz[1] 
                         && iter_n>dim_ker[1]-1
                         && iter_n<dim_im[1]-dim_ker[1]+1){
                  nb_sum=2;
                  for (int ind1=pos_n-k; k<max_k; k++,ind1--) {
                    sum+=idx_hvals[k]*idx_in[ind1];
                    sum2+=idx_hvals[k]*idx_in[ind1+%(self_dy)s];
                  }
                }else{
                  nb_sum=1;
                  /*
                  %(type)s sum_=0;
                  if((k-max_k) & 0x1 != 0){
                    sum+= idx_hvals[k] * idx_in[pos_n-k];
                  }
                  for (int ind1=pos_n-k; k<max_k; k+=2,ind1-=2) {
                    sum+= idx_hvals[k] * idx_in[ind1];
                    sum_+= idx_hvals[k+1] * idx_in[ind1-1];
                  }
                  sum+=sum_;
                  */
                  for (int ind1=pos_n-k; k<max_k; k++,ind1--) {
                    sum+=idx_hvals[k]*idx_in[ind1];
                  }
                }
                //do the part to the left of the img
                if(fill_value!=0)
                  for(;k<dim_ker[1];k++) sum+= idx_hvals[k]*fill_value;
              }
            }else{//valid mode
              const %(type)s* idx_in=&in[ind0*dim_im[1]];
              const %(type)s* idx_hvals=&hvals[j*dim_ker[1]];
              if(iter_n + 4*%(self_dy)s < dim_zz[1]){
                nb_sum=4;
                for (int k=dim_ker[1]-1,im_idx=pos_n; k >=0; k--,im_idx++) {
                  sum+=idx_hvals[k]*idx_in[im_idx];
                  sum2+=idx_hvals[k]*idx_in[im_idx+%(self_dy)s];
                  sum3+=idx_hvals[k]*idx_in[im_idx+2*%(self_dy)s];
                  sum4+=idx_hvals[k]*idx_in[im_idx+3*%(self_dy)s];
                }
              }else if(iter_n + 2*%(self_dy)s < dim_zz[1]){
                nb_sum=2;
                for (int k=dim_ker[1]-1,im_idx=pos_n; k >=0; k--,im_idx++) {
                  sum+=idx_hvals[k]*idx_in[im_idx];
                  sum2+=idx_hvals[k]*idx_in[im_idx+%(self_dy)s];
                }
              }else{
                nb_sum=1;
                for (int k=dim_ker[1]-1,im_idx=pos_n; k >=0; k--,im_idx++) {
                  sum+=idx_hvals[k]*idx_in[im_idx];
                }
              }
            }//else valid mode
          }//for j
          switch(nb_sum){
          case 4: out[iter_m*dim_zz[1]+iter_n+3] %(affectation)s sum4;
          case 3: out[iter_m*dim_zz[1]+iter_n+2] %(affectation)s sum3;
          case 2: out[iter_m*dim_zz[1]+iter_n+1] %(affectation)s sum2;
          case 1: out[iter_m*dim_zz[1]+iter_n] %(affectation)s sum;
          }
          iter_n+=nb_sum-1;
        }//for iter_n
      }//for iter_m
    }//for stack_size
  }//for n_kern
}//for b
Py_XDECREF(img2d);
Py_XDECREF(filtersflipped);
"""
