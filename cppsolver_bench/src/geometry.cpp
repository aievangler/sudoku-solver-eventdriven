#include "geometry.hpp"
#include <cstring>

namespace geom {

std::array<int,81> ROW{};
std::array<int,81> COL{};
std::array<int,81> BOX{};
std::array<std::array<int,3>,81> CELL_UNITS{};

std::array<Bits81, 9> ROW_MASK{};
std::array<Bits81, 9> COL_MASK{};
std::array<Bits81, 9> BOX_MASK{};
std::array<Bits81,81> PEER_MASK{};
std::array<Bits81,27> UNIT_MASK{};
std::array<std::array<Bits81,3>,9> BOX_ROW_MASK{};
std::array<std::array<Bits81,3>,9> BOX_COL_MASK{};

static inline void set(Bits81& b, int idx){
    if(idx < 64) b.lo |= (1ULL<<idx);
    else b.hi |= (1ULL<<(idx-64));
}

void init(){
    // rows, cols, boxes
    for(int r=0; r<9; ++r){
        for(int c=0; c<9; ++c){
            int idx = r*9 + c;
            ROW[idx] = r;
            COL[idx] = c;
            int b = (r/3)*3 + (c/3);
            BOX[idx] = b;
        }
    }
    // unit masks
    for(int r=0;r<9;++r){
        Bits81 m{};
        for(int c=0;c<9;++c) set(m, r*9+c);
        ROW_MASK[r] = m;
        UNIT_MASK[r] = m; // units 0..8 rows
    }
    for(int c=0;c<9;++c){
        Bits81 m{};
        for(int r=0;r<9;++r) set(m, r*9+c);
        COL_MASK[c] = m;
        UNIT_MASK[9+c] = m; // units 9..17 cols
    }
    for(int br=0;br<3;++br){
        for(int bc=0; bc<3; ++bc){
            int b = br*3 + bc;
            Bits81 m{};
            for(int dr=0; dr<3; ++dr){
                for(int dc=0; dc<3; ++dc){
                    int r = br*3 + dr;
                    int c = bc*3 + dc;
                    set(m, r*9+c);
                }
            }
            BOX_MASK[b] = m;
            UNIT_MASK[18+b] = m; // 18..26 boxes
        }
    }
    // CELL_UNITS (row, col, box unit ids)
    for(int i=0;i<81;++i){
        CELL_UNITS[i][0] = ROW[i];           // row unit id 0..8
        CELL_UNITS[i][1] = 9 + COL[i];       // col unit id 9..17
        CELL_UNITS[i][2] = 18 + BOX[i];      // box unit id 18..26
    }
    // PEER_MASK: all cells sharing row or col or box (excluding self)
    for(int i=0;i<81;++i){
        Bits81 m{};
        auto r = ROW[i], c = COL[i], b = BOX[i];
        // row
        for(int cc=0; cc<9; ++cc){ int j=r*9+cc; if(j!=i) set(m, j); }
        // col
        for(int rr=0; rr<9; ++rr){ int j=rr*9+c; if(j!=i) set(m, j); }
        // box
        int br = (r/3)*3, bc = (c/3)*3;
        for(int dr=0; dr<3; ++dr){
            for(int dc=0; dc<3; ++dc){
                int j = (br+dr)*9 + (bc+dc);
                if(j!=i) set(m, j);
            }
        }
        PEER_MASK[i] = m;
    }
    // BOX_ROW_MASK / BOX_COL_MASK
    for(int b=0;b<9;++b){
        int br = (b/3)*3, bc = (b%3)*3;
        for(int rr=0; rr<3; ++rr){
            Bits81 m{};
            for(int dc=0; dc<3; ++dc){
                int r = br+rr, c = bc+dc;
                set(m, r*9+c);
            }
            BOX_ROW_MASK[b][rr] = m;
        }
        for(int cc=0; cc<3; ++cc){
            Bits81 m{};
            for(int dr=0; dr<3; ++dr){
                int r = br+dr, c = bc+cc;
                set(m, r*9+c);
            }
            BOX_COL_MASK[b][cc] = m;
        }
    }
}

} // namespace geom
